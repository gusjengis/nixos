#!/usr/bin/env python3
"""Port of SkyLight's desktop-affinity color and AppKit's Chameleon material.

See desktop-tint/README.md for extraction provenance. No dominant-color palette,
blur, saturation boost, or Liquid Glass setting participates in this material.
"""

import argparse
import fcntl
import functools
import io
import json
import math
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import tempfile
import time

SAMPLE_SCALE = 0.125
QUANTIZATION_BITS = 6
FILL = 0.11759999394416809
OPACITY = 0.10000000149011612


def intersection(a, b):
    x, y = max(a[0], b[0]), max(a[1], b[1])
    w = min(a[0] + a[2], b[0] + b[2]) - x
    h = min(a[1] + a[3], b[1] + b[3]) - y
    return (x, y, max(0, w), max(0, h))


class Payload:
    """Inclusive float32 integral image, with SkyLight's aligned row stride."""

    def __init__(self, pixels, rect, scale=SAMPLE_SCALE):
        import numpy as np

        self.rect, self.scale = rect, scale
        height, width = pixels.shape[:2]
        self.stride = (width + 3) & ~3
        integral = np.asarray(pixels, dtype=np.float32).cumsum(1).cumsum(0)
        self.sat = np.zeros((height, self.stride, 4), dtype=np.float32)
        self.sat[:, :width] = integral
        self.sat = self.sat.reshape(-1, 4)

    def average(self, rect):
        import numpy as np

        rect = intersection(rect, self.rect)
        x, y = ((rect[i] - self.rect[i]) * self.scale for i in (0, 1))
        w, h = rect[2] * self.scale, rect[3] * self.scale
        if w <= 0 or h <= 0:
            return np.zeros(4, dtype=np.float32)
        left, top = int(x), int(y) - 1
        right, bottom = left + int(w) - 1, top + int(h)

        def at(column, row):
            index = row * self.stride + column
            if index < 0 or index >= len(self.sat):
                return np.zeros(4, dtype=np.float32)
            return self.sat[index]

        # This is deliberately x, not x-1. Confirmed by invoking Apple's
        # Payload::average_color with a synthetic integral image (see fixture).
        a = at(left, top) if left and top >= 0 else np.zeros(4, dtype=np.float32)
        b = at(right, top) if top >= 0 else np.zeros(4, dtype=np.float32)
        c = at(left, bottom) if left else np.zeros(4, dtype=np.float32)
        d = at(right, bottom)
        mean = np.clip(((a + d) - b - c) / (np.float32(w) * np.float32(h)), 0, 1)
        levels = 1 << QUANTIZATION_BITS
        return np.minimum(np.floor(mean * np.float32(levels)), levels - 1) * np.float32(1 / (levels - 1))


def average_color(payloads, rect):
    import numpy as np

    samples = []
    for payload in payloads:
        region = intersection(rect, payload.rect)
        area = np.float32(region[2] * region[3])
        if area > 0:
            samples.append((payload.average(region), area))
    total = sum((area for _, area in samples), np.float32(0))
    result = np.zeros(4, dtype=np.float32)
    for tone, area in samples:
        result += tone * np.float32(area / total)
    return result


@functools.lru_cache(maxsize=1)
def gamut_matrices():
    import numpy as np

    def rgb_to_xyz(primaries):
        columns = np.array([[x / y, 1, (1 - x - y) / y] for x, y in primaries]).T
        white = np.array([0.3127 / 0.3290, 1, (1 - 0.3127 - 0.3290) / 0.3290])
        return columns @ np.diag(np.linalg.solve(columns, white))

    srgb = rgb_to_xyz(((.64, .33), (.30, .60), (.15, .06)))
    p3 = rgb_to_xyz(((.68, .32), (.265, .69), (.15, .06)))
    forward = np.linalg.solve(p3, srgb)
    return forward, np.linalg.inv(forward)


def convert_gamut(rgb, matrix):
    import numpy as np

    linear = np.array([c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb])
    return [12.92 * c if c <= .0031308 else 1.055 * c ** (1 / 2.4) - .055 for c in matrix @ linear]


def material(tone, base=(FILL, FILL, FILL)):
    """CAChameleon source-over in the reference Mac's encoded Display P3.

    Native side-by-side captures distinguish this from mixing in sRGB or in
    linear light. Return sRGB for GTK/Qt; the compositor then manages the local
    display, including HDR, without changing the reference material's gamut.
    """
    alpha = float(tone[3])
    if alpha <= 0:
        return list(base)
    forward, inverse = gamut_matrices()
    color = convert_gamut([float(c) / alpha for c in tone[:3]], forward)
    fill = convert_gamut(base, forward)
    mixed = [fill[i] * (1 - alpha * OPACITY) + color[i] * alpha * OPACITY for i in range(3)]
    return [max(0, min(1, c)) for c in convert_gamut(mixed, inverse)]


def palette(tone):
    return {
        "tone": list(map(float, tone)),
        "surface": material(tone),
        "card": material(tone, (54 / 255, 54 / 255, 57 / 255)),
        "hover": material(tone, (69 / 255, 69 / 255, 72 / 255)),
        "border": material(tone, (74 / 255, 74 / 255, 77 / 255)),
        "footer": material(tone, (48 / 255,) * 3),
    }


def load_wallpaper(path):
    from PIL import Image, ImageCms, ImageOps

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        profile = image.info.get("icc_profile")
        if profile:
            image = ImageCms.profileToProfile(image.convert("RGB"), ImageCms.ImageCmsProfile(io.BytesIO(profile)), ImageCms.createProfile("sRGB"), outputMode="RGB")
        return image.convert("RGBA")


def make_payload(image, monitor):
    import numpy as np
    from PIL import Image

    width, height = monitor["width"], monitor["height"]
    if monitor.get("transform", 0) % 2:
        width, height = height, width
    logical_width, logical_height = width / monitor["scale"], height / monitor["scale"]
    rect = (monitor["x"], monitor["y"], logical_width, logical_height)
    cover = max(width / image.width, height / image.height)
    # Match the two raster stages: wallpaper cover, then the compositor's
    # linear-filtered, non-antialiased SimpleTexture copy to BGRA8Unorm.
    rendered = image.transform((width, height), Image.Transform.AFFINE,
        (1 / cover, 0, (image.width - width / cover) / 2,
         0, 1 / cover, (image.height - height / cover) / 2), Image.Resampling.BILINEAR)
    small = (math.ceil(logical_width * SAMPLE_SCALE), math.ceil(logical_height * SAMPLE_SCALE))
    sampled = rendered.transform(small, Image.Transform.AFFINE,
        (width / small[0], 0, 0, 0, height / small[1], 0), Image.Resampling.BILINEAR)
    return Payload(np.asarray(sampled, dtype=np.float32) / np.float32(255), rect)


def atomic_json(path, data):
    value = json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n"
    try:
        if path.read_text() == value:
            return
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".desktop-tint-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(value)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def hyprland(kind):
    # A user service can start without the compositor's shell environment.
    # Resolve only an unambiguous instance (or the explicitly selected display),
    # then keep that identity even while disposable nested compositors appear.
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        instances = json.loads(subprocess.check_output(["hyprctl", "instances", "-j"], timeout=2, stderr=subprocess.DEVNULL))
        display = os.environ.get("WAYLAND_DISPLAY")
        matches = [item for item in instances if item.get("wl_socket") == display] if display else []
        candidates = matches or instances
        if len(candidates) != 1:
            raise ValueError("cannot identify the desktop's Hyprland instance")
        os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = candidates[0]["instance"]
    try:
        return json.loads(subprocess.check_output(["hyprctl", "-j", kind], timeout=2, stderr=subprocess.DEVNULL))
    except subprocess.CalledProcessError:
        os.environ.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
        raise


def state_directory():
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "wallpaper"


def socket_path():
    return Path(os.environ["XDG_RUNTIME_DIR"]) / "desktop-tint.sock"


def active_wallpapers():
    # Older wallpaperctl processes do not publish `displayed`, and callers can
    # set hyprpaper directly. Its live IPC is authoritative, including previews.
    try:
        output = subprocess.check_output(["hyprctl", "hyprpaper", "listactive"],
            timeout=2, stderr=subprocess.DEVNULL, text=True)
    except (OSError, subprocess.SubprocessError):
        return {}
    result = {}
    for line in output.splitlines():
        monitor, separator, path = line.partition(": ")
        if separator and Path(path).is_absolute():
            result[monitor] = path
    return result


def watch():
    state = state_directory()
    lock = open(socket_path().with_suffix(".lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    socket_path().unlink(missing_ok=True)
    server = socket.socket(socket.AF_UNIX)
    server.bind(str(socket_path()))
    os.chmod(socket_path(), 0o600)
    server.listen(8)
    server.setblocking(False)
    selector = selectors.DefaultSelector()
    selector.register(server, selectors.EVENT_READ)
    payloads, monitors, fingerprint = [], [], None
    active = {}
    generation, next_tick = 0, 0
    next_monitors, next_clients = 0, 0
    clients, cached_windows = [], {}
    default, default_key = palette([0, 0, 0, 0]), None
    last_error = None
    try:
        while True:
            for key, _ in selector.select(max(0, next_tick - time.monotonic())):
                connection, _ = key.fileobj.accept()
                with connection:
                    connection.settimeout(0.5)
                    try:
                        request = json.loads(connection.recv(4096))
                        region = list(map(float, request["rect"]))
                        if len(region) != 4 or not all(math.isfinite(v) for v in region):
                            raise ValueError("invalid region")
                        result = palette(average_color(payloads, region))
                        connection.sendall((json.dumps(result) + "\n").encode())
                    except (ValueError, KeyError, OSError):
                        pass
            now = time.monotonic()
            if now < next_tick:
                continue
            next_tick = now + 0.1
            try:
                if now >= next_monitors:
                    monitors = hyprland("monitors")
                    active = active_wallpapers()
                    next_monitors = now + 1
                displayed = (state / "displayed").read_text().strip() if (state / "displayed").exists() else ""
                wallpapers = [Path(active.get(m["name"]) or displayed or (state / "current").read_text().strip())
                    for m in monitors]
                files = [(str(path), path.stat().st_mtime_ns, path.stat().st_size) for path in wallpapers]
                geometry = [(m["name"], m["x"], m["y"], m["width"], m["height"], m["scale"], m.get("transform", 0)) for m in monitors]
                stamp = (files, geometry)
                if stamp != fingerprint:
                    images = {path: load_wallpaper(path) for path in set(wallpapers)}
                    payloads = [make_payload(images[path], m) for path, m in zip(wallpapers, monitors)]
                    del images
                    fingerprint, generation = stamp, time.time_ns() // 1_000_000
                focused = next((i for i, m in enumerate(monitors) if m.get("focused")), 0)
                if default_key != (generation, focused):
                    default = palette(payloads[focused].average(payloads[focused].rect)) if payloads else palette([0, 0, 0, 0])
                    default_key = generation, focused
                if now >= next_clients:
                    clients = [client for client in hyprland("clients")
                        if "strata" in client.get("class", "").lower() and client.get("mapped")]
                    next_clients = now + (0.1 if clients else 1)
                windows = []
                new_cache = {}
                for client in clients:
                    rect = client["at"] + client["size"]
                    key = (client["pid"], client["title"], tuple(rect), generation)
                    colors = cached_windows.get(key)
                    if colors is None:
                        colors = palette(average_color(payloads, rect))
                    new_cache[key] = colors
                    windows.append({"pid": client["pid"], "title": client["title"], "width": rect[2], "height": rect[3],
                        **colors})
                cached_windows = new_cache
                atomic_json(state / "desktop-tint.json", {"generation": generation, "default": default, "windows": windows})
                last_error = None
            except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
                message = str(error)
                if message != last_error:
                    print("desktop-tint:", message, file=sys.stderr, flush=True)
                    last_error = message
    finally:
        server.close()
        socket_path().unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("watch", "sample"))
    parser.add_argument("rect", nargs="*", type=float)
    args = parser.parse_args()
    if args.mode == "watch":
        watch()
    else:
        if len(args.rect) != 4:
            parser.error("sample requires global x y width height")
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(2)
            client.connect(str(socket_path()))
            client.sendall(json.dumps({"rect": args.rect}).encode())
            with client.makefile() as stream:
                print(stream.readline().strip())


if __name__ == "__main__":
    main()
