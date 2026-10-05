"""Delete a raw note and everything generated from it, on request only.

Raw notes are the record, so nothing in the pipeline deletes notes on its own:
a half-synced vault would look exactly like deliberate deletions. This is the
explicit action instead.

    note-delete --latest            newest raw note
    note-delete 2026-10-02-140939   by stem
    note-delete --orphans           generated notes whose raw note is gone

It lists what it will remove and asks first (`--yes` skips the question).
Obsidian Sync carries the deletion to every other device.
"""

import argparse
import re
import sys
from pathlib import Path

EMBED = re.compile(r"!\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
# Folders holding notes generated from a raw note, named like the raw note.
GENERATED = ["Normalized"]


def targets_for(vault: Path, stem: str) -> list[Path]:
    raw = vault / "Raw" / f"{stem}.md"
    if not raw.is_file():
        sys.exit(f"no raw note {raw}")
    paths = [raw]
    for match in EMBED.finditer(raw.read_text(encoding="utf-8")):
        image = vault / match.group(1).strip()
        if image.is_file() and image.parent == vault / "Raw" / "Images":
            paths.append(image)
    for folder in GENERATED:
        generated = vault / folder / f"{stem}.md"
        if generated.is_file():
            paths.append(generated)
    return paths


def orphans(vault: Path) -> list[Path]:
    return [
        note
        for folder in GENERATED
        for note in sorted((vault / folder).glob("*.md"))
        if not (vault / "Raw" / note.name).exists()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault", type=Path, required=True)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("stem", nargs="?", help="raw note name, e.g. 2026-10-02-140939")
    which.add_argument("--latest", action="store_true", help="newest raw note")
    which.add_argument("--orphans", action="store_true", help="generated notes without a raw note")
    parser.add_argument("--yes", action="store_true", help="do not ask")
    args = parser.parse_args()

    if args.orphans:
        paths = orphans(args.vault)
    else:
        if args.latest:
            notes = sorted((args.vault / "Raw").glob("*.md"))
            if not notes:
                sys.exit("no raw notes")
            stem = notes[-1].stem
        else:
            stem = args.stem.removesuffix(".md")
        paths = targets_for(args.vault, stem)
        print((args.vault / "Raw" / f"{stem}.md").read_text(encoding="utf-8").strip())
        print()

    if not paths:
        print("nothing to delete")
        return
    for path in paths:
        print(f"delete {path.relative_to(args.vault)}")
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("not a terminal; pass --yes to confirm")
        if input("Delete these? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("cancelled")
    for path in paths:
        path.unlink(missing_ok=True)
    print(f"deleted {len(paths)} file(s)")


if __name__ == "__main__":
    main()
