#!/usr/bin/env python3
"""Fetch Peapix Spotlight metadata for the wallpapers in ~/Wallpapers.

Wallpapers named ``windows-spotlight-<id>.<ext>`` map directly onto
``https://peapix.com/spotlight/<id>``. Metadata is merged into
``~/Wallpapers/metadata.json`` keyed by file name so the picker can search it.
"""

import html
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


WALLPAPER_DIR = Path.home() / "Wallpapers"
METADATA_FILE = WALLPAPER_DIR / "metadata.json"
SOURCE_URL = "https://peapix.com/spotlight/{identifier}"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) wallpaper-metadata/1.0"
SPOTLIGHT_NAME = re.compile(r"^windows-spotlight-(\d+)$")
EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}

TITLE_PATTERN = re.compile(r'<h1 class="fs-4 fw-bold[^"]*">(.*?)</h1>', re.DOTALL)
COPYRIGHT_PATTERN = re.compile(r'<h1 class="fs-4 fw-bold[^"]*">.*?</h1>\s*<p class="[^"]*">(.*?)</p>', re.DOTALL)
HEADLINE_PATTERN = re.compile(r'<h3 class="mb-4 fs-6">(.*?)</h3>', re.DOTALL)
BODY_PATTERN = re.compile(r'<div class="position-relative mb-4">(.*?)</div>', re.DOTALL)
PARAGRAPH_PATTERN = re.compile(r"<p>(.*?)</p>", re.DOTALL)
DATE_PATTERN = re.compile(r'<time datetime="([^"]+)"')
TAGS_PATTERN = re.compile(r'<div class="tag-list">(.*?)</div>', re.DOTALL)
TAG_PATTERN = re.compile(r'<a class="tag-list__item[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
TAG_MARKUP = re.compile(r"<[^>]+>")


def clean(raw):
    return html.unescape(TAG_MARKUP.sub("", raw)).strip()


def fetch(url, attempts=4):
    last_error = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
            if isinstance(error, urllib.error.HTTPError) and error.code == 404:
                return None
            last_error = error
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last_error}")


def parse(page):
    title = TITLE_PATTERN.search(page)
    copyright_notice = COPYRIGHT_PATTERN.search(page)
    headline = HEADLINE_PATTERN.search(page)
    date = DATE_PATTERN.search(page)
    body = BODY_PATTERN.search(page)
    tag_block = TAGS_PATTERN.search(page)

    paragraphs = []
    if body:
        paragraphs = [clean(paragraph) for paragraph in PARAGRAPH_PATTERN.findall(body.group(1))]

    tags = []
    if tag_block:
        tags = [clean(tag) for tag in TAG_PATTERN.findall(tag_block.group(1))]

    return {
        "title": clean(title.group(1)) if title else "",
        "headline": clean(headline.group(1)) if headline else "",
        "description": "\n\n".join(paragraph for paragraph in paragraphs if paragraph),
        "copyright": clean(copyright_notice.group(1)) if copyright_notice else "",
        "date": date.group(1) if date else "",
        "tags": [tag for tag in tags if tag],
    }


def spotlight_targets():
    targets = {}
    for path in sorted(WALLPAPER_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            continue
        match = SPOTLIGHT_NAME.match(path.stem)
        if match:
            targets[path.name] = match.group(1)
    return targets


def load_existing():
    try:
        stored = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return stored.get("entries", {}) if isinstance(stored, dict) else {}


def save(entries):
    payload = {
        "version": 1,
        "source": "https://peapix.com/spotlight",
        "entries": dict(sorted(entries.items())),
    }
    temporary = METADATA_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    temporary.replace(METADATA_FILE)


def main():
    refresh = "--refresh" in sys.argv[1:]
    targets = spotlight_targets()
    entries = {} if refresh else load_existing()
    pending = {name: identifier for name, identifier in targets.items() if name not in entries}

    print(f"{len(targets)} spotlight wallpapers, {len(pending)} to fetch", file=sys.stderr)
    if not pending:
        save(entries)
        return

    failures = []

    def work(item):
        name, identifier = item
        url = SOURCE_URL.format(identifier=identifier)
        page = fetch(url)
        if page is None:
            return name, None
        record = parse(page)
        record["id"] = identifier
        record["url"] = url
        return name, record

    completed = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, record in pool.map(work, sorted(pending.items())):
            completed += 1
            if record is None or not record["title"]:
                failures.append(name)
            else:
                entries[name] = record
            if completed % 25 == 0:
                print(f"  {completed}/{len(pending)}", file=sys.stderr)
                save(entries)

    save(entries)
    print(f"wrote {len(entries)} entries to {METADATA_FILE}", file=sys.stderr)
    if failures:
        print(f"missing metadata for {len(failures)}: {', '.join(failures[:20])}", file=sys.stderr)


if __name__ == "__main__":
    main()
