"""Delete a raw note and everything generated from it, on request only.

Raw notes are the record, so nothing in the pipeline deletes notes on its own:
a half-synced vault would look exactly like deliberate deletions. This is the
explicit action instead.

    note-delete --latest            newest raw note
    note-delete 2026-10-02-140939   by stem
    note-delete --orphans           generated notes whose raw note is gone

Thoughts extracted from the note (notes/DATA_MODEL.md, Deletion) are found by
their `source` property: a thought whose only source is the note is deleted,
one with other sources only loses that source. Links to deleted thoughts are
removed from the remaining thoughts and entities.

It lists what it will do and asks first (`--yes` skips the question).
Obsidian Sync carries the deletion to every other device.
"""

import argparse
import re
import sys
from pathlib import Path

EMBED = re.compile(r"!\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
LINK = re.compile(r"\[\[([^\]|#]+)")
# Folders holding notes generated from a raw note, named like the raw note.
GENERATED = ["Normalized"]
# Folders of extracted notes, linked to their sources by frontmatter.
EXTRACTED = ["Thoughts", "Entities"]


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


# Frontmatter is edited as text, list item by list item, so everything else
# in the note (user fields, formatting) is left exactly as it was. The
# extractor writes block lists; Obsidian does too.


def frontmatter(text: str) -> tuple[list[str], str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return text[4:end].split("\n"), text[end:]


def link_target(value: str) -> str | None:
    match = LINK.search(value)
    return match.group(1).strip().removesuffix(".md") if match else None


def list_items(lines: list[str], key: str) -> list[int]:
    """Line numbers of the block list items under `key`."""
    for i, line in enumerate(lines):
        if line.startswith(key + ":"):
            items = []
            for j in range(i + 1, len(lines)):
                if re.match(r"\s+- ", lines[j]) or lines[j].startswith("- "):
                    items.append(j)
                elif lines[j].strip():
                    break
            return items
    return []


def flow_to_block(lines: list[str]) -> list[str]:
    """Rewrite `key: ["[[a]]", "[[b]]"]` link lists as block lists."""
    out = []
    for line in lines:
        match = re.match(r"([\w-]+):\s*\[(.*\[\[.*)\]\s*$", line)
        if not match:
            out.append(line)
            continue
        out.append(f"{match.group(1)}:")
        for item in re.findall(r"""("[^"]*"|'[^']*'|[^,]+)""", match.group(2)):
            if item.strip():
                out.append(f"  - {item.strip()}")
    return out


def sources(lines: list[str]) -> list[str]:
    return [t for t in (link_target(lines[i]) for i in list_items(lines, "source")) if t]


def drop_links(lines: list[str], gone: set[str], keys: set[str] | None = None) -> list[str]:
    """Remove list items linking to `gone`, under `keys` or any key."""
    drop = set()
    current = None
    for i, line in enumerate(lines):
        if re.match(r"[\w-]+:", line):
            current = line.split(":", 1)[0]
        elif (keys is None or current in keys) and re.match(r"\s*- ", line):
            if link_target(line) in gone:
                drop.add(i)
    return [line for i, line in enumerate(lines) if i not in drop]


def extracted_plan(vault: Path, gone_sources: set[str]) -> tuple[list[Path], dict[Path, str]]:
    """Thoughts to delete, and notes to rewrite (path -> new text)."""
    delete: list[Path] = []
    rewrite: dict[Path, str] = {}
    notes = {
        path: frontmatter(path.read_text(encoding="utf-8"))
        for folder in EXTRACTED
        for path in sorted((vault / folder).glob("*.md"))
    }
    notes = {path: parts for path, parts in notes.items() if parts}
    for path, (lines, rest) in notes.items():
        if path.parent.name != "Thoughts":
            continue
        lines = flow_to_block(lines)
        own = sources(lines)
        if not own or not set(own) & gone_sources:
            continue
        if set(own) <= gone_sources:
            delete.append(path)
            continue
        lines = drop_links(lines, gone_sources, {"source"})
        left = len(sources(lines))
        lines = [f"mentions_count: {left}" if l.startswith("mentions_count:") else l for l in lines]
        rewrite[path] = "---\n" + "\n".join(lines) + rest
    gone_notes = {f"{p.parent.name}/{p.stem}" for p in delete}
    if gone_notes:
        for path, (lines, rest) in notes.items():
            if path in delete:
                continue
            if path in rewrite:
                lines, rest = frontmatter(rewrite[path])
            new = drop_links(flow_to_block(lines), gone_notes)
            if new != lines:
                rewrite[path] = "---\n" + "\n".join(new) + rest
    return delete, rewrite


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault", type=Path, required=True)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("stem", nargs="?", help="raw note name, e.g. 2026-10-02-140939")
    which.add_argument("--latest", action="store_true", help="newest raw note")
    which.add_argument("--orphans", action="store_true", help="generated notes without a raw note")
    parser.add_argument("--yes", action="store_true", help="do not ask")
    args = parser.parse_args()
    vault = args.vault

    if args.orphans:
        paths = orphans(vault)
        # Every source that no longer exists, or is about to be deleted.
        referenced = {
            source
            for path in sorted((vault / "Thoughts").glob("*.md"))
            if (parts := frontmatter(path.read_text(encoding="utf-8")))
            for source in sources(flow_to_block(parts[0]))
        }
        gone = {s for s in referenced if not (vault / f"{s}.md").exists()}
        gone |= {f"{p.parent.name}/{p.stem}" for p in paths}
    else:
        if args.latest:
            notes = sorted((vault / "Raw").glob("*.md"))
            if not notes:
                sys.exit("no raw notes")
            stem = notes[-1].stem
        else:
            stem = args.stem.removesuffix(".md")
        paths = targets_for(vault, stem)
        gone = {f"Normalized/{stem}"}
        print((vault / "Raw" / f"{stem}.md").read_text(encoding="utf-8").strip())
        print()

    thoughts, rewrite = extracted_plan(vault, gone)
    paths += thoughts
    if not paths and not rewrite:
        print("nothing to delete")
        return
    for path in paths:
        print(f"delete {path.relative_to(vault)}")
    for path in rewrite:
        print(f"update {path.relative_to(vault)} (drop links to deleted notes)")
    if not args.yes:
        if not sys.stdin.isatty():
            sys.exit("not a terminal; pass --yes to confirm")
        if input("Go ahead? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("cancelled")
    for path, text in rewrite.items():
        path.write_text(text, encoding="utf-8")
    for path in paths:
        path.unlink(missing_ok=True)
    print(f"deleted {len(paths)} file(s), updated {len(rewrite)}")


if __name__ == "__main__":
    main()
