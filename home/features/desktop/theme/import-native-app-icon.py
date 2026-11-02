#!/usr/bin/env python3
"""Add reviewed native PNG/ICNS artwork to the persistent source inventory.

Run with the same Pillow-enabled Python environment as macos-icons, then run
macos-icons to publish aliases. Modern bundles may require rendering on macOS:
their ICNS can be an older fallback for Assets.car/Icon Composer artwork.
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artwork", type=Path)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--method", required=True, help="How the native artwork was extracted")
    parser.add_argument("--archive-sha256")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent / "icon-source"
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    payload = args.artwork.read_bytes()
    image = Image.open(BytesIO(payload)).convert("RGBA")
    if not image.getchannel("A").getbbox():
        raise ValueError("Empty icon")
    files = {}
    for size in (16, 32, 48, 64, 128, 256, 512):
        buffer = BytesIO()
        image.resize((size, size), Image.Resampling.LANCZOS).save(buffer, format="PNG")
        png = buffer.getvalue()
        relative = "png/" + hashlib.sha256(png).hexdigest() + ".png"
        if not (source / relative).exists():
            (source / relative).write_bytes(png)
        files[str(size)] = relative
    entry = {
        "kind": "app", "id": args.bundle_id, "source": args.source_url,
        "files": files, "provenance": {
            "method": args.method, "artwork_sha256": hashlib.sha256(payload).hexdigest(),
        },
    }
    if args.archive_sha256:
        entry["provenance"]["archive_sha256"] = args.archive_sha256
    # A downloaded bundle supplements the existing Mac inventory. Replacing an
    # existing identity requires deliberate review rather than silent takeover.
    existing = [e for e in manifest["entries"] if e["kind"] == "app" and e["id"] == args.bundle_id]
    if existing:
        if existing == [entry]:
            print(f"Unchanged: {args.bundle_id}")
            return
        raise ValueError(f"Already imported: {args.bundle_id}; review the existing entry first")
    manifest["entries"].append(entry)
    temporary = manifest_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    temporary.replace(manifest_path)
    print(f"Imported {args.bundle_id}: {image.width}x{image.height}, {len(files)} sizes")


if __name__ == "__main__":
    main()
