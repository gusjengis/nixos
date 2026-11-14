#!/usr/bin/env python3
"""Build Finder's non-empty folder icon (papers showing) for the native theme.

Input: the composites from export-finder-folder-components.swift, run on the
Mac (`swift export-finder-folder-components.swift <dir>`), which stacks
CoreTypes' FolderComponent_{BackFlap,PaperSheet,FrontFlap} artwork.
Output: icon-source/finder/folder-full-<size>.png, aligned so that only the
paper differs from the theme's own places/folder.png at each size.
Requires Pillow.
"""
import argparse
from pathlib import Path

from PIL import Image

SIZES = (16, 32, 48, 64, 128, 256, 512)
ROOT = Path(__file__).resolve().parent


def solid_bounds(image):
    return image.getchannel("A").point(lambda value: 255 if value >= 250 else 0).getbbox()


def build(components: Path, theme: Path, output: Path):
    output.mkdir(parents=True, exist_ok=True)
    full = Image.open(components / "folder-full-512.png").convert("RGBA")
    empty = Image.open(components / "folder-empty-512.png").convert("RGBA")
    empty_bounds = solid_bounds(empty)
    for size in SIZES:
        folder = Image.open(theme / f"{size}x{size}/places/folder.png").convert("RGBA")
        bounds = solid_bounds(folder)
        sx = (bounds[2] - bounds[0]) / (empty_bounds[2] - empty_bounds[0])
        sy = (bounds[3] - bounds[1]) / (empty_bounds[3] - empty_bounds[1])
        scaled = (round(full.width * sx), round(full.height * sy))
        offset = (round(bounds[0] - empty_bounds[0] * sx), round(bounds[1] - empty_bounds[1] * sy))
        full_layer = Image.new("RGBA", folder.size)
        full_layer.paste(full.resize(scaled, Image.Resampling.LANCZOS), offset)
        empty_layer = Image.new("RGBA", folder.size)
        empty_layer.paste(empty.resize(scaled, Image.Resampling.LANCZOS), offset)
        # Keep the theme's own folder pixels except where the paper shows.
        result = folder.copy()
        out, new, old = result.load(), full_layer.load(), empty_layer.load()
        for y in range(size):
            for x in range(size):
                if max(abs(a - b) for a, b in zip(new[x, y], old[x, y])) > 2:
                    out[x, y] = new[x, y]
        result.save(output / f"folder-full-{size}.png")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("components", type=Path)
    parser.add_argument("--theme", type=Path, default=ROOT / "icons/MacOS-Native")
    parser.add_argument("--output", type=Path, default=ROOT / "icon-source/finder")
    args = parser.parse_args()
    build(args.components, args.theme, args.output)
