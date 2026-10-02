"""Import completed Supernote batches into Obsidian as raw notes.

Each outbox batch holds capture.md (transcript body with ![[page image]]
embeds), capture.json ({"created": ISO time}) and the page images. The note
itself is made by capture-note, which executes the vault's raw note template;
this script only supplies the facts (text, source, time) and the page images,
which are named after the note: Raw/Images/<note>-page-NN.png.
"""

import argparse
import json
import re
import secrets
import subprocess
from pathlib import Path

BATCH = re.compile(r"[0-9a-f]{64}")
IMAGE = re.compile(r"Capture-[0-9a-f]{64}-page-([0-9]+)\.png")
# Batches written before capture.json existed carry their own frontmatter and
# embed images by vault path.
EMBED = re.compile(r"!\[\[(?:Raw/Images/)?(Capture-[0-9a-f]{64}-page-[0-9]+\.png)\]\]")
LEGACY_FRONTMATTER = re.compile(r"---\n(.*?\n)---\n", re.DOTALL)
IMAGES_DIR = "Raw/Images"


def read_batch(batch: Path) -> tuple[str, str]:
    body = (batch / "capture.md").read_text(encoding="utf-8")
    meta = batch / "capture.json"
    if meta.exists():
        return body, json.loads(meta.read_text(encoding="utf-8"))["created"]
    legacy = LEGACY_FRONTMATTER.match(body)
    if not legacy:
        raise ValueError(f"{batch} has no capture.json")
    created = re.search(r"^created: (.+)$", legacy.group(1), re.M).group(1)
    return body[legacy.end() :], created


def import_batch(batch: Path, vault: Path, capture_note: str) -> str:
    body, created = read_batch(batch)
    # Stands in for the note name, which only the template decides.
    token = f"capture-{secrets.token_hex(8)}"
    attachments = []

    def embed(match: re.Match) -> str:
        image = batch / match.group(1)
        page = IMAGE.fullmatch(image.name)
        if not page or not image.exists():
            raise ValueError(f"{batch} embeds missing image {image.name}")
        name = f"{token}-page-{page.group(1)}.png"
        attachments.append(f"--attach={image}={name}")
        return f"![[{IMAGES_DIR}/{name}]]"

    body = EMBED.sub(embed, body)
    result = subprocess.run(
        [
            capture_note,
            "--vault", str(vault),
            "--source", "supernote",
            "--created", created,
            "--name-token", token,
            "--attach-dir", IMAGES_DIR,
            *attachments,
        ],
        input=body,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"capture-note failed for {batch}: {result.stderr.strip()}")
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outbox", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--capture-note", default="capture-note")
    args = parser.parse_args()
    if not args.outbox.is_dir():
        return
    for batch in sorted(args.outbox.iterdir()):
        if not batch.is_dir() or not BATCH.fullmatch(batch.name):
            continue
        if (batch / ".imported").exists() or not (batch / "capture.md").exists():
            continue
        note = import_batch(batch, args.vault, args.capture_note)
        (batch / ".imported").write_text(f"{note}\n", encoding="utf-8")
        print(f"imported {batch.name} as {note}", flush=True)


if __name__ == "__main__":
    main()
