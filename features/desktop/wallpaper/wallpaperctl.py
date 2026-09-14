#!/usr/bin/env python3

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path


WALLPAPER_DIR = Path.home() / "Wallpapers"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "wallpaper"
CURRENT_FILE = STATE_DIR / "current"
ORDER_FILE = STATE_DIR / "order.json"
COLORS_FILE = STATE_DIR / "colors.json"
EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def wallpapers():
    if not WALLPAPER_DIR.is_dir():
        return []
    return sorted(
        path.resolve()
        for path in WALLPAPER_DIR.rglob("*")
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in EXTENSIONS
    )


def save_order(available):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = ORDER_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps([str(path) for path in available]), encoding="utf-8")
    temporary.replace(ORDER_FILE)


def randomized_order(available):
    try:
        stored = json.loads(ORDER_FILE.read_text(encoding="utf-8"))
        ordered = [Path(path).resolve() for path in stored]
    except (json.JSONDecodeError, OSError, RuntimeError, TypeError):
        ordered = []

    if len(ordered) == len(available) and set(ordered) == set(available):
        return ordered

    ordered = list(available)
    random.SystemRandom().shuffle(ordered)
    save_order(ordered)
    return ordered


def current():
    try:
        path = Path(CURRENT_FILE.read_text(encoding="utf-8").strip()).resolve()
    except (OSError, RuntimeError):
        return None
    return path if path in wallpapers() else None


def ensure_daemon():
    if subprocess.run(["awww", "query"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return

    subprocess.Popen(
        ["awww-daemon", "--quiet"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(40):
        time.sleep(0.05)
        if subprocess.run(["awww", "query"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return
    raise RuntimeError("awww-daemon did not become ready")


def generate_colors(path):
    result = subprocess.run(
        [
            "matugen",
            "--mode", "dark",
            "--type", "scheme-tonal-spot",
            "--source-color-index", "0",
            "--dry-run",
            "--json", "hex",
            "image", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    generated = json.loads(result.stdout)
    colors = generated["colors"]
    palettes = generated["palettes"]

    def color(name):
        return colors[name]["dark"]["color"]

    return {
        "background": color("background"),
        "surface": color("surface_container"),
        "surfaceHover": color("surface_container_high"),
        "text": color("on_surface"),
        "muted": color("on_surface_variant"),
        "accent": color("primary"),
        "accentStrong": palettes["primary"]["70"]["color"],
        "warning": color("tertiary"),
        "danger": color("error"),
        "border": color("outline_variant"),
    }


def write_state(path, colors):
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    colors_temporary = COLORS_FILE.with_suffix(".tmp")
    colors_temporary.write_text(json.dumps(colors), encoding="utf-8")
    colors_temporary.replace(COLORS_FILE)

    current_temporary = CURRENT_FILE.with_suffix(".tmp")
    current_temporary.write_text(f"{path}\n", encoding="utf-8")
    current_temporary.replace(CURRENT_FILE)


def set_wallpaper(raw_path, immediate=False, persist=True):
    path = Path(raw_path).expanduser().resolve()
    available = wallpapers()
    if path not in available:
        raise ValueError(f"wallpaper is not a supported image under {WALLPAPER_DIR}: {path}")

    colors = generate_colors(path) if persist else None
    ensure_daemon()
    command = ["awww", "img", str(path), "--resize", "crop"]
    if immediate:
        command.extend(["--transition-type", "none"])
    else:
        command.extend([
            "--transition-type", "fade",
            "--transition-duration", "0.35",
            "--transition-fps", "60",
        ])
    subprocess.run(command, check=True)

    if persist:
        write_state(path, colors)
    return path


def choose_next(available, active):
    index = available.index(active) if active in available else -1
    return available[(index + 1) % len(available)]


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    available = randomized_order(wallpapers())
    active = current()

    if command == "catalog":
        print(json.dumps({
            "current": str(active) if active else "",
            "wallpapers": [
                {"name": path.stem, "path": str(path), "extension": path.suffix[1:].upper()}
                for path in available
            ],
        }))
        return
    if command == "current":
        print(active or "")
        return
    if command == "set" and len(sys.argv) == 3:
        print(set_wallpaper(sys.argv[2]))
        return
    if command == "preview" and len(sys.argv) == 3:
        print(set_wallpaper(sys.argv[2], persist=False))
        return
    if command == "random":
        if available:
            print(set_wallpaper(choose_next(available, active)))
        return
    if command == "next":
        if available:
            print(set_wallpaper(choose_next(available, active)))
        return
    if command == "restore":
        if active:
            print(set_wallpaper(active, immediate=True))
        elif available:
            print(set_wallpaper(choose_next(available, None), immediate=True))
        return

    print("usage: wallpaperctl {catalog|current|set PATH|preview PATH|random|next|restore}", file=sys.stderr)
    raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except (json.JSONDecodeError, KeyError, OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as error:
        print(f"wallpaperctl: {error}", file=sys.stderr)
        raise SystemExit(1)
