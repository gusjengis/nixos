"""Matugen palette generation, cached in ~/Wallpapers/metadata.json.

Running matugen against a full-resolution image takes ~0.2-0.3s. wallpaperctl
(Rust) never pays that cost: it only ever reads the "palette" field cached
here, keyed by file name. This module is used by generate-palettes.py, the
manual/periodic script that actually calls matugen and backfills the cache.
"""

import json
import os
import subprocess
from pathlib import Path

# Overridable so the scheduled CI job, which has no ~/Wallpapers, can point the
# whole toolchain at its checkout without any code changes.
WALLPAPER_DIR = Path(os.environ.get("WALLPAPER_DIR") or Path.home() / "Wallpapers")
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
    # Serialise a sorted *copy*. Rebinding metadata["entries"] would orphan the
    # live dict callers hold across checkpoints: entries added after the first
    # save would be written to a dict nobody serialises again and silently lost.
    payload = dict(metadata)
    payload["entries"] = dict(sorted(metadata["entries"].items()))
    temporary = METADATA_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(METADATA_FILE)


def store(filename, colors):
    """Persist a computed palette into metadata.json, preserving other fields."""
    metadata = load_metadata()
    metadata["entries"].setdefault(filename, {})["palette"] = colors
    save_metadata(metadata)
