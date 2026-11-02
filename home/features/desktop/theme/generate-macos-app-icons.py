#!/usr/bin/env python3
"""Fill MacOS-Native's missing app icons with static macOS-style squircles.

Requires Pillow and CairoSVG. Native imported icons are never replaced.
Outputs seven PNG sizes, a source manifest, and an icon-preview.png contact sheet.
"""
import argparse
import colorsys
import configparser
import hashlib
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import subprocess

import cairosvg
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

SIZES = (16, 32, 48, 64, 128, 256, 512)
RENDER_VERSION = "squircle-v3-color"
ORIGINAL_ICON = "X-MacOS-Native-Original-Icon"
ORIGINAL_DESKTOP = "X-MacOS-Native-Original-Desktop"
# Reviewed exceptions for multicolor marks and logos whose small accent should
# not determine the entire plate. Other apps derive their palette from artwork.
BACKGROUND_PALETTES = {
    "f3d": ("#d8d6f4", "#a9a4da"),
    "webapp-google-photos": ("#d6e8f5", "#9fc4e3"),
    "webapp-calendar": ("#d4e4f8", "#9bbce9"),
    "vicinae": ("#40434e", "#20232c"),
    "webapp-supernote": ("#494563", "#29263c"),
    "cups": ("#445266", "#273344"),
    "kdeconnect": ("#43546a", "#263347"),
    "virt-manager": ("#cad5e4", "#98aac2"),
    "org.pwmt.zathura": ("#444b60", "#252d40"),
    "webapp-qobuz": ("#41495c", "#242b3a"),
}


def atomic_write(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == contents:
        return False
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(contents)
        if path.exists():
            temporary.chmod(path.stat().st_mode & 0o777)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def desktop_config(path):
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.optionxform = str
    config.read(path)
    return config


def data_roots():
    return list(dict.fromkeys([
        Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")),
        *(Path(path) for path in os.environ.get("XDG_DATA_DIRS", "").split(":") if path),
        Path.home() / ".local/share/flatpak/exports/share", Path("/var/lib/flatpak/exports/share"),
        Path.home() / ".nix-profile/share", Path("/run/current-system/sw/share"),
        Path("/usr/local/share"), Path("/usr/share"),
    ]))


def applications(roots):
    seen = set()
    for root in roots:
        for desktop in sorted((root / "applications").glob("*.desktop")):
            if desktop.name in seen:
                continue
            seen.add(desktop.name)
            try:
                config = desktop_config(desktop)
                app = config["Desktop Entry"]
                if ORIGINAL_DESKTOP in app:
                    original = Path(app[ORIGINAL_DESKTOP])
                    if original != desktop:
                        if not original.is_file():
                            desktop.unlink()
                            seen.remove(desktop.name)
                            continue
                        config = desktop_config(original)
                        app = config["Desktop Entry"]
                        desktop = original
                if app.getboolean("Hidden", fallback=False) or app.getboolean("NoDisplay", fallback=False):
                    continue
                yield app.get("Name", desktop.stem), app.get(ORIGINAL_ICON, app.get("Icon", "")), desktop
            except (configparser.Error, ValueError):
                continue


def icon_directories(roots):
    # Prefer the app's own art; use existing Linux themes when none was shipped.
    directories = []
    for theme in ("hicolor", "Papirus", "Colloid", "Adwaita", "breeze"):
        for root in roots:
            base = root / "icons" / theme
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read(base / "index.theme")
            if not config.has_section("Icon Theme"):
                continue
            sections = config["Icon Theme"].get("Directories", "").split(",")
            sections += config["Icon Theme"].get("ScaledDirectories", "").split(",")
            sections = [name for name in sections if name and config.has_section(name)]
            sections.sort(key=lambda name: (
                config[name].get("Context", "").lower() != "applications",
                -int(config[name].get("Size", "0")),
            ))
            directories.extend(base / name for name in sections)
    directories.extend(root / "pixmaps" for root in roots)
    return list(dict.fromkeys(directories))


def resolve_icon(name, directories):
    if Path(name).is_absolute():
        return Path(name) if Path(name).is_file() else None
    if not name or "/" in name:
        return None
    for directory in directories:
        for extension in (".svg", ".png", ".xpm", ""):
            candidate = directory / (name + extension)
            if candidate.is_file():
                return candidate
    return None


def load_icon(path):
    if path.suffix.lower() == ".svg":
        data = cairosvg.svg2png(url=str(path), output_width=512, output_height=512)
        image = Image.open(BytesIO(data)).convert("RGBA")
    else:
        image = Image.open(path).convert("RGBA")
    bounds = image.getchannel("A").getbbox()
    if not bounds:
        raise ValueError(f"Empty icon: {path}")
    return image.crop(bounds)


def squircle_mask(size=1024):
    mask = Image.new("L", (size, size))
    points = []
    # Continuous superellipse, with margins reserved for the external shadow.
    for step in range(1440):
        angle = step * 2 * math.pi / 1440
        x, y = math.cos(angle), math.sin(angle)
        points.append((size * (0.5 + 0.47 * math.copysign(abs(x) ** (2 / 4.6), x)),
                       size * (0.485 + 0.47 * math.copysign(abs(y) ** (2 / 4.6), y))))
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask


def background_colors(logo, identity=""):
    """Choose a related hue and a light/dark plate by visible-art contrast.

    Transparent RGB is deliberately ignored. Hue buckets prevent complementary
    logo colors averaging into gray; neutral artwork gets a restrained slate hue.
    Light plates remain colored rather than defaulting to white.
    """
    if identity in BACKGROUND_PALETTES:
        return BACKGROUND_PALETTES[identity]
    pixels = [(r / 255, g / 255, b / 255, a / 255)
              for r, g, b, a in logo.resize((64, 64)).get_flattened_data() if a >= 128]
    if not pixels:
        raise ValueError("Empty icon")

    def luminance(rgb):
        linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
        return sum(v * weight for v, weight in zip(linear, (0.2126, 0.7152, 0.0722)))

    buckets = [0.0] * 24
    for r, g, b, alpha in pixels:
        hue, saturation, value = colorsys.rgb_to_hsv(r, g, b)
        if saturation > 0.20 and value > 0.18:
            buckets[int(hue * 24) % 24] += alpha * saturation * value
    saturation = 0.48
    if sum(buckets) > sum(pixel[3] for pixel in pixels) * 0.08:
        hue = (max(range(24), key=buckets.__getitem__) + 0.5) / 24
    else:
        hue, saturation = 0.59, 0.22
    # Modest analogous shift separates the plate from same-hue foreground art.
    hue = (hue + 0.045) % 1
    candidates = [(colorsys.hls_to_rgb(hue, 0.27, saturation), colorsys.hls_to_rgb(hue, 0.15, saturation)),
                  (colorsys.hls_to_rgb(hue, 0.84, saturation), colorsys.hls_to_rgb(hue, 0.71, saturation))]
    foreground = [(luminance((r, g, b)), alpha) for r, g, b, alpha in pixels]

    def score(colors):
        # Geometric mean contrast rewards separation without letting a few white
        # highlights outweigh the main logo. Check both ends of the gradient.
        return min(sum(alpha * math.log((max(light, luminance(color)) + 0.05) /
                                        (min(light, luminance(color)) + 0.05))
                       for light, alpha in foreground) for color in colors)

    selected = max(candidates, key=score)
    return tuple(tuple(round(channel * 255) for channel in color) for color in selected)


def render_icon(logo, *, centered=False, identity=""):
    size = 1024
    mask = squircle_mask(size)
    gradient = Image.linear_gradient("L").resize((size, size))
    colors = background_colors(logo, identity)
    background = ImageOps.colorize(gradient, *colors).convert("RGBA")
    plate = Image.new("RGBA", (size, size))
    plate.paste(background, mask=mask)

    alpha = logo.getchannel("A")
    occupancy = alpha.resize((64, 64)).point(lambda value: 255 if value > 220 else 0)
    opaque_fraction = sum(occupancy.histogram()[1:]) / (64 * 64)
    already_tile = not centered and 0.9 < logo.width / logo.height < 1.1 and opaque_fraction > 0.88
    extent = round(size * (0.94 if already_tile else 0.66))
    artwork = ImageOps.contain(logo, (extent, extent), Image.Resampling.LANCZOS)
    foreground = Image.new("RGBA", (size, size))
    foreground.alpha_composite(artwork, ((size - artwork.width) // 2, round(size * 0.485 - artwork.height / 2)))
    if not already_tile:
        logo_shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        shadow_alpha = foreground.getchannel("A").filter(ImageFilter.GaussianBlur(4)).point(lambda value: value // 5)
        logo_shadow.putalpha(ImageChops.offset(shadow_alpha, 0, 4))
        plate = Image.alpha_composite(plate, logo_shadow)
    plate = Image.alpha_composite(plate, foreground)
    plate.putalpha(ImageChops.multiply(plate.getchannel("A"), mask))

    # Fine raised edge, with light from above; deliberately no animated glass.
    edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(5)))
    highlight = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    highlight.putalpha(ImageChops.multiply(edge, ImageOps.invert(gradient)).point(lambda value: value // 2))
    plate = Image.alpha_composite(plate, highlight)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shadow = ImageChops.offset(mask, 0, 9).filter(ImageFilter.GaussianBlur(10)).point(lambda value: value // 4)
    result.putalpha(shadow)
    return Image.alpha_composite(result, plate).resize((512, 512), Image.Resampling.LANCZOS)


def gallery(theme, generated, output):
    font_path = subprocess.check_output(["fc-match", "-f", "%{file}", "SF Pro"], text=True)
    font = ImageFont.truetype(font_path, 13)
    heading = ImageFont.truetype(font_path, 23)
    native = [("Finder", "org.xfce.thunar"), ("Obsidian", "obsidian"), ("Slack", "slack"),
              ("ChatGPT", "webapp-chatgpt"), ("Outlook", "webapp-outlook"), ("Zoom", "Zoom")]
    columns, cell_w, cell_h = 6, 176, 132
    rows = math.ceil(len(generated) / columns)
    sheet = Image.new("RGB", (columns * cell_w + 32, 260 + rows * cell_h), "#20242d")
    draw = ImageDraw.Draw(sheet)
    draw.text((20, 14), "Native icons extracted from your Mac", font=heading, fill="white")
    for index, (label, icon) in enumerate(native):
        path = theme / "128x128/apps" / f"{icon}.png"
        if path.exists():
            image = Image.open(path).convert("RGBA").resize((80, 80), Image.Resampling.LANCZOS)
            sheet.paste(image, (16 + index * cell_w + 48, 52), image)
            draw.text((16 + index * cell_w + 88, 140), label, font=font, fill="white", anchor="mt")
    draw.text((20, 184), "Generated Linux icons  ·  original → squircle", font=heading, fill="white")
    for index, entry in enumerate(generated):
        x, y = 16 + (index % columns) * cell_w, 230 + (index // columns) * cell_h
        original = theme / entry["artwork"] if entry.get("artwork") else Path(entry["source"])
        old = ImageOps.contain(load_icon(original), (40, 40), Image.Resampling.LANCZOS)
        new = Image.open(theme / "128x128/apps" / f"{entry['icon']}.png").convert("RGBA").resize((80, 80), Image.Resampling.LANCZOS)
        sheet.paste(old, (x + 10 + (40 - old.width) // 2, y + 20 + (40 - old.height) // 2), old)
        draw.text((x + 61, y + 40), "→", font=font, fill="#9aa5b7", anchor="mm")
        sheet.paste(new, (x + 78, y), new)
        label = entry["name"]
        while draw.textlength(label, font=font) > cell_w - 12:
            label = label[:-2] + "…"
        draw.text((x + cell_w // 2, y + 88), label, font=font, fill="white", anchor="mt")
    output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output)


def absolute_override(desktop, original_icon, icon, data):
    target = data / "applications" / desktop.name
    if target.exists() and target != desktop:
        existing = desktop_config(target)["Desktop Entry"]
        if ORIGINAL_DESKTOP not in existing:
            raise ValueError(f"Refusing to replace an unmanaged launcher: {target}")
    text = desktop.read_text()
    # Change only Desktop Entry's Icon; preserve Exec, actions, localization,
    # Steam URLs and all other application-provided metadata verbatim.
    match = re.search(r"(?m)^\[Desktop Entry\]\s*$", text)
    if not match:
        raise ValueError(f"Missing Desktop Entry: {desktop}")
    start = match.end()
    following = re.search(r"(?m)^\[", text[start:])
    end = start + following.start() if following else len(text)
    section = text[start:end]
    section = re.sub(r"(?m)^(?:Icon|X-MacOS-Native-Original-Icon|X-MacOS-Native-Original-Desktop)=.*\n?", "", section)
    section = section.rstrip() + f"\nIcon={icon}\n{ORIGINAL_ICON}={original_icon}\n{ORIGINAL_DESKTOP}={desktop}\n"
    changed = atomic_write(target, (text[:start] + section + text[end:]).encode())
    return target, changed


def generate(theme, preview=None, *, preserve_library=False):
    if not (theme / "index.theme").exists():
        raise ValueError("Build the native theme before generating missing app icons")
    roots = data_roots()
    data = roots[0]
    manifest_path = theme / "generated-apps.json"
    previous = json.loads(manifest_path.read_text()) if manifest_path.exists() else []
    # Shells and systemd can expose different XDG directories. Retain observed
    # application roots so a background scan cannot undo a valid shell import.
    roots = list(dict.fromkeys([*roots, *(Path(entry["desktop"]).parent.parent for entry in previous
        if Path(entry["desktop"]).parent.name == "applications")]))
    directories = icon_directories(roots)
    previous_by_name = {entry["icon"]: entry for entry in previous}
    generated, skipped, seen, changed = [], [], set(), 0
    native_overrides = set()
    native_desktops = set()
    for name, requested_icon, desktop in applications(roots):
        if not requested_icon:
            continue
        absolute = Path(requested_icon).is_absolute()
        icon = "macos-native-absolute-" + hashlib.sha256(desktop.name.encode()).hexdigest()[:16] if absolute else requested_icon
        # Absolute Icon= paths bypass theme lookup. A curated native alias for
        # this exact launcher identity should still win (e.g. arduino.desktop).
        if absolute and (theme / f"48x48/apps/{desktop.stem}.png").is_symlink():
            icon = desktop.stem
        if icon in seen:
            continue
        seen.add(icon)
        target = theme / "48x48/apps" / f"{icon}.png"
        if target.is_symlink() or (target.exists() and icon not in previous_by_name):
            native_desktops.add(str(desktop))
            if absolute:
                override, override_changed = absolute_override(desktop, requested_icon, icon, data)
                native_overrides.add(str(override))
                changed += int(override_changed)
            continue
        source = resolve_icon(requested_icon, directories)
        if not source:
            skipped.append({"name": name, "reason": "source icon not found"})
            if icon in previous_by_name:
                generated.append(previous_by_name[icon])
            continue
        try:
            fingerprint = hashlib.sha256(RENDER_VERSION.encode() + icon.encode() + source.read_bytes()).hexdigest()
            previous_entry = previous_by_name.get(icon, {})
            complete = all((theme / f"{size}x{size}/apps/{icon}.png").is_file() for size in SIZES)
            artwork_path = previous_entry.get("artwork")
            needs_artwork = not artwork_path or not (theme / artwork_path).exists()
            original = None
            if fingerprint != previous_entry.get("fingerprint") or not complete or needs_artwork:
                original = load_icon(source)
                capture = BytesIO()
                original.save(capture, format="PNG")
                payload = capture.getvalue()
                artwork_path = "app-sources/" + hashlib.sha256(payload).hexdigest() + ".png"
                atomic_write(theme / artwork_path, payload)
            if fingerprint != previous_entry.get("fingerprint") or not complete:
                image = render_icon(original, centered=icon == "webapp-calendar", identity=icon)
                for size in SIZES:
                    path = theme / f"{size}x{size}/apps" / f"{icon}.png"
                    if path.is_symlink():
                        raise RuntimeError(f"Refusing to replace imported native icon: {path}")
                    buffer = BytesIO()
                    image.resize((size, size), Image.Resampling.LANCZOS).save(buffer, format="PNG")
                    atomic_write(path, buffer.getvalue())
                changed += 1
            entry = {"name": name, "icon": icon, "desktop": str(desktop), "source": str(source),
                     "fingerprint": fingerprint, "artwork": artwork_path}
            if absolute:
                override, override_changed = absolute_override(desktop, requested_icon, icon, data)
                entry["override"] = str(override)
                changed += int(override_changed)
            generated.append(entry)
        except (OSError, ValueError) as error:
            skipped.append({"name": name, "reason": str(error)})
            if icon in previous_by_name:
                generated.append(previous_by_name[icon])
            continue
    current_names = {entry["icon"] for entry in generated}
    for old in previous:
        if old["icon"] in current_names:
            continue
        if (preserve_library and old["desktop"] not in native_desktops
                and not (theme / f"48x48/apps/{old['icon']}.png").is_symlink()):
            # The repo is an icon library, not a per-machine cache: absence of
            # an app on another host must not delete versioned artwork.
            retained = dict(old)
            retained.pop("override", None)
            generated.append(retained)
            if old.get("override"):
                path = Path(old["override"])
                if path.is_file():
                    original = desktop_config(path)["Desktop Entry"].get(ORIGINAL_DESKTOP)
                    if original and Path(original) != path and not Path(original).exists():
                        path.unlink()
            continue
        for size in SIZES:
            path = theme / f"{size}x{size}/apps/{old['icon']}.png"
            if path.is_file() and not path.is_symlink():
                path.unlink()
                changed += 1
        if old.get("override") and old["override"] not in native_overrides:
            path = Path(old["override"])
            if path.is_file() and ORIGINAL_DESKTOP in desktop_config(path)["Desktop Entry"]:
                path.unlink()
    generated.sort(key=lambda entry: entry["icon"])
    atomic_write(manifest_path, (json.dumps(generated, indent=2) + "\n").encode())
    if preview:
        gallery(theme, generated, preview)
    print(f"Generated set: {len(generated)} app icons; {changed} changed; skipped {len(skipped)}.", flush=True)
    for entry in skipped:
        print(f"  Skipped {entry['name']}: {entry['reason']}")
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("theme", type=Path)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    generate(args.theme, args.preview, preserve_library=True)


if __name__ == "__main__":
    main()
