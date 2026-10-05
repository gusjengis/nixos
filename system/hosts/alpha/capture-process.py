"""Render and transcribe archived Supernote captures into a durable outbox."""

import argparse
import base64
import datetime
import json
import os
import re
import subprocess
import tempfile
import urllib.request
from pathlib import Path


def transcribe(image: Path, url: str, model: str) -> str:
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "messages": [
            {
                "role": "user",
                # Raw notes stay a faithful record: wording is never corrected
                # here (the omega normalizer does that), but layout the eye can
                # see on the page, indentation and strike-through, is kept.
                "content": (
                    "Transcribe all handwritten text on this page exactly, as Markdown. "
                    "Keep the original line breaks. Reproduce indentation: nested list "
                    "items are indented 4 spaces per level relative to their parent. "
                    "Wrap crossed-out text in ~~ ~~. Do not correct spelling or wording. "
                    "Return only the transcription, no commentary. If the page has "
                    "no handwriting, return nothing at all: no explanation, no "
                    "placeholder."
                ),
                "images": [base64.b64encode(image.read_bytes()).decode("ascii")],
            }
        ],
        "options": {"temperature": 0},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        answer = json.load(response)
    text = answer["message"]["content"].strip()
    return "" if is_blank_reply(text) else text


# Vision models asked to return nothing for a blank page sometimes explain
# instead ("The provided image is completely blank..."). A short reply that
# only talks about the page being empty is treated as no text.
BLANK_REPLY = re.compile(
    r"(\b(image|page|note)\b.{0,40}\b(is|appears|seems)\b.{0,20}\b(blank|empty)\b"
    r"|\bno (handwritten|visible|legible) (text|writing)\b|\bno handwriting\b"
    r"|\bnothing to transcribe\b)",
    re.IGNORECASE,
)


def is_blank_reply(text: str) -> bool:
    # Real notes are lists; a model explaining itself writes plain sentences.
    first = text.lstrip()[:1]
    return (
        len(text) < 200
        and first not in ("-", "*", "+", "~")
        and not first.isdigit()
        and bool(BLANK_REPLY.search(text))
    )


# Written for blank pages by earlier versions; still ignored when comparing.
BLANK_MARKER = "*[No text recognized on this page]*"


def transcript_key(markdown: str) -> str:
    """Normalized transcript text: frontmatter, embeds and blank markers removed.

    Tablets rewrite notebooks on every sync, so re-uploads of unchanged
    handwriting arrive with different bytes; deduplicate on the words instead.
    """
    body = (
        markdown.split("\n---\n", 1)[-1] if markdown.startswith("---\n") else markdown
    )
    lines = [
        line
        for line in body.splitlines()
        if not line.startswith("![[") and line.strip() != BLANK_MARKER
    ]
    return " ".join(" ".join(lines).lower().split())


def known_transcripts(outbox: Path) -> dict[str, str]:
    known = {}
    for batch in sorted(outbox.iterdir()):
        source = batch / "capture.md"
        if batch.is_dir() and source.exists():
            key = transcript_key(source.read_text(encoding="utf-8"))
            known.setdefault(key, batch.name)
    return known


def skip(stage: Path, destination: Path, reason: str) -> None:
    # A batch without capture.md is never imported, but records the decision so
    # the archive is not reprocessed.
    for image in stage.glob("*.png"):
        image.unlink()
    (stage / "skipped").write_text(reason + "\n", encoding="utf-8")
    os.rename(stage, destination)


def process(archive: Path, outbox: Path, renderer: str, url: str, model: str) -> None:
    capture_id = archive.stem.removeprefix("Capture-")
    if not re.fullmatch(r"[0-9a-f]{64}", capture_id):
        raise ValueError(f"unexpected archive name: {archive.name}")
    destination = outbox / capture_id
    if destination.exists():
        return

    with tempfile.TemporaryDirectory(prefix=".capture-", dir=outbox) as stage_name:
        stage = Path(stage_name)
        metadata = json.loads(
            subprocess.check_output(
                [renderer, "analyze", str(archive)],
                text=True,
            )
        )
        count = len(metadata["__pages__"])
        if count == 0:
            raise ValueError(f"notebook has no pages: {archive}")
        body = []
        for page in range(count):
            image_name = f"Capture-{capture_id}-page-{page + 1:02d}.png"
            image = stage / image_name
            subprocess.run(
                [renderer, "convert", "-n", str(page), str(archive), str(image)],
                check=True,
            )
            text = transcribe(image, url, model)
            # A blank page keeps its image, with no text at all.
            body.append(f"{text}\n\n![[{image_name}]]" if text else f"![[{image_name}]]")

        created = (
            datetime.datetime.fromtimestamp(
                archive.stat().st_mtime, datetime.timezone.utc
            )
            .astimezone()
            .isoformat(timespec="seconds")
        )
        # Body only: the pc import renders the note from the vault's raw note
        # template, so the note format is defined in one place.
        markdown = "\n\n".join(body) + "\n"
        key = transcript_key(markdown)
        if not key:
            skip(stage, destination, "blank: no text recognized on any page")
            print(f"skipped blank capture {capture_id}", flush=True)
            return
        duplicate = known_transcripts(outbox).get(key)
        if duplicate:
            skip(stage, destination, f"duplicate of {duplicate}")
            print(f"skipped duplicate capture {capture_id} of {duplicate}", flush=True)
            return
        (stage / "capture.md").write_text(markdown, encoding="utf-8")
        (stage / "capture.json").write_text(
            json.dumps({"created": created}) + "\n", encoding="utf-8"
        )
        os.rename(stage, destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--outbox-dir", type=Path, required=True)
    parser.add_argument("--renderer", required=True)
    parser.add_argument("--ocr-url", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    args.outbox_dir.mkdir(parents=True, exist_ok=True)
    failed = False
    # Oldest first, so the earliest upload of a thought is the one kept.
    archives = sorted(
        args.archive_dir.glob("Capture-*.note"), key=lambda p: p.stat().st_mtime
    )
    for archive in archives:
        try:
            process(archive, args.outbox_dir, args.renderer, args.ocr_url, args.model)
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
            print(f"capture processing failed for {archive}: {exc}", flush=True)
            failed = True
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
