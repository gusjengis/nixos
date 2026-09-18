#!/usr/bin/env python3
"""Backfill matugen palettes for every wallpaper into ~/Wallpapers/metadata.json.

wallpaperctl.py computes a palette lazily (cache miss -> matugen -> cache),
so this script only exists to warm the whole cache up front instead of
paying the ~0.2-0.3s matugen cost one wallpaper at a time as they're
scrolled past in the picker. Run with --push to commit and push the
resulting metadata.json to the wallpaper repo.
"""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import palette

WALLPAPER_DIR = Path.home() / "Wallpapers"
EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}


def wallpapers():
    return sorted(
        path
        for path in WALLPAPER_DIR.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in EXTENSIONS
    )


def main():
    refresh = "--refresh" in sys.argv[1:]
    push = "--push" in sys.argv[1:]

    files = wallpapers()
    metadata = palette.load_metadata()
    entries = metadata["entries"]

    if refresh:
        pending = files
    else:
        pending = [path for path in files if not (entries.get(path.name) or {}).get("palette")]

    print(f"{len(files)} wallpapers, {len(pending)} to compute", file=sys.stderr)
    if not pending:
        return

    failures = []
    completed = 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(palette.compute, path): path for path in pending}
        for future in as_completed(futures):
            path = futures[future]
            completed += 1
            try:
                colors = future.result()
            except Exception as error:  # noqa: BLE001 - report and keep going
                failures.append(path.name)
                print(f"  failed: {path.name}: {error}", file=sys.stderr)
                continue
            entries.setdefault(path.name, {})["palette"] = colors
            if completed % 25 == 0:
                print(f"  {completed}/{len(pending)}", file=sys.stderr)
                palette.save_metadata(metadata)

    palette.save_metadata(metadata)
    print(f"wrote palettes for {len(pending) - len(failures)} wallpapers to {palette.METADATA_FILE}", file=sys.stderr)
    if failures:
        print(f"failed for {len(failures)}: {', '.join(failures[:20])}", file=sys.stderr)

    if push:
        subprocess.run(["git", "-C", str(WALLPAPER_DIR), "add", "metadata.json"], check=True)
        status = subprocess.run(
            ["git", "-C", str(WALLPAPER_DIR), "diff", "--cached", "--quiet"],
        )
        if status.returncode == 0:
            print("no metadata.json changes to commit", file=sys.stderr)
            return
        subprocess.run(
            ["git", "-C", str(WALLPAPER_DIR), "commit", "-m", "Cache matugen palettes in metadata.json"],
            check=True,
        )
        subprocess.run(["git", "-C", str(WALLPAPER_DIR), "push"], check=True)


if __name__ == "__main__":
    main()
