"""Matugen palette generation, cached in ~/Wallpapers/metadata.json.

Running matugen against a full-resolution image takes ~0.2-0.3s, which used
to sit directly in the hot path every time a wallpaper was previewed or set.
Palettes almost never change for a given image, so they are cached in the
same metadata.json used for Peapix titles/tags, keyed by file name. A cache
hit is a plain dict lookup; only a never-before-seen wallpaper pays the
matugen cost, and that result is persisted for next time.
"""

import json
import subprocess
from pathlib import Path

WALLPAPER_DIR = Path.home() / "Wallpapers"
METADATA_FILE = WALLPAPER_DIR / "metadata.json"


def compute(path):
    """Run matugen against path and return the theme palette. Slow (~0.2-0.3s)."""
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


def load_metadata():
    try:
        stored = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    stored.setdefault("version", 1)
    stored.setdefault("source", "https://peapix.com/spotlight")
    stored.setdefault("entries", {})
    return stored


def save_metadata(metadata):
    metadata["entries"] = dict(sorted(metadata["entries"].items()))
    temporary = METADATA_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(METADATA_FILE)


def cached(filename):
    """Return the cached palette for filename, or None on a cache miss."""
    entry = load_metadata()["entries"].get(filename)
    return entry.get("palette") if entry else None


def store(filename, colors):
    """Persist a computed palette into metadata.json, preserving other fields."""
    metadata = load_metadata()
    metadata["entries"].setdefault(filename, {})["palette"] = colors
    save_metadata(metadata)


def get_or_compute(path):
    """Cache-first palette lookup; falls back to matugen and persists the result."""
    filename = Path(path).name
    colors = cached(filename)
    if colors is not None:
        return colors
    colors = compute(path)
    store(filename, colors)
    return colors
