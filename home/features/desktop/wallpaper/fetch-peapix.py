#!/usr/bin/env python3
"""Backfill ~/Wallpapers with every native-4K image published on peapix.com.

Peapix has two sections, ``/bing/<id>`` and ``/spotlight/<id>``, and no usable
archive API: the JSON feeds ignore their date parameters and the HTML listings
hard-cap at 50 pages. So ids are enumerated directly.

Three facts drive the design:

* A bing image is republished under one id per country (~11.5 ids/day for
  ~2.5 distinct images). The ``og:image`` key is shared by every one of those
  ids, so grouping on it removes ~80% of the download set.
* ``<key>_UHD.jpg`` always answers 3840x2160, but it *upscales* low-resolution
  originals, so it cannot be used to decide whether an image is really 4K.
  The bare ``<key>.jpg`` is the native file, and a 64 KiB ranged GET is enough
  to read its JPEG SOF header. Only images at least 3840x2160 are kept.
* Bing originals below id ~36000 (early 2022) are all 1366x768 / 1920x1080,
  which is why the default bing range starts there.

Discovery and header probes are cached as append-only JSONL under
``$XDG_CACHE_HOME/peapix`` so an interrupted run resumes without refetching.
"""

import argparse
import html
import http.client
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

WALLPAPER_DIR = Path(os.environ.get("WALLPAPER_DIR") or Path.home() / "Wallpapers")
METADATA_FILE = WALLPAPER_DIR / "metadata.json"
CACHE_DIR = Path(
    os.environ.get("WALLPAPER_CACHE_DIR")
    or Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "peapix"
)
PAGES_CACHE = CACHE_DIR / "pages.jsonl"
DIMENSIONS_CACHE = CACHE_DIR / "dimensions.jsonl"

SITE_HOST = "peapix.com"
IMAGE_HOST = "img.peapix.com"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) wallpaper-metadata/2.0"
TIMEOUT = 40

MINIMUM_WIDTH = 3840
MINIMUM_HEIGHT = 2160
# A JPEG's SOF segment normally sits within the first few KiB, but peapix
# serves files carrying chained XMP blocks that push it past 800 KiB. Probing
# escalates through these ranges, then gives up and pulls the whole file,
# rather than mistaking an unreadable header for a sub-4K image.
HEADER_PROBE_SIZES = [65535, 1 << 20, None]

# Filenames are per-section so the existing spotlight collection keeps working.
NAME_TEMPLATES = {
    "spotlight": "windows-spotlight-{identifier}.jpg",
    "bing": "bing-{identifier}.jpg",
}
KNOWN_NAMES = re.compile(r"^(?:windows-spotlight|bing)-(\d+)$")
EXTENSIONS = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}

KEY_PATTERN = re.compile(r'og:image"\s+content="https://img\.peapix\.com/([^_"]+)_\d+\.jpg"')
COUNTRY_PATTERN = re.compile(
    r'<a class="nav-link[^"]*\bactive\b[^"]*"[^>]*href="/bing/([a-z]{2})"'
)
TITLE_PATTERN = re.compile(r'<h1 class="fs-4 fw-bold[^"]*">(.*?)</h1>', re.DOTALL)
COPYRIGHT_PATTERN = re.compile(
    r'<h1 class="fs-4 fw-bold[^"]*">.*?</h1>\s*<p class="[^"]*">(.*?)</p>', re.DOTALL
)
HEADLINE_PATTERN = re.compile(r'<h3 class="mb-4 fs-6">(.*?)</h3>', re.DOTALL)
DATE_PATTERN = re.compile(r'<time datetime="([^"]+)"')
TAGS_PATTERN = re.compile(r'<div class="tag-list">(.*?)</div>', re.DOTALL)
TAG_PATTERN = re.compile(r'<a class="tag-list__item[^"]*"[^>]*>(.*?)</a>', re.DOTALL)
PARAGRAPH_PATTERN = re.compile(r"<p>(.*?)</p>", re.DOTALL)
TAG_MARKUP = re.compile(r"<[^>]+>")

# Standalone JPEG markers carry no length field, so the segment walk must not
# try to read one for them.
STANDALONE_MARKERS = {0x01, 0xD8, 0xD9} | set(range(0xD0, 0xD8))
SOF_MARKERS = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def clean(raw):
    return html.unescape(TAG_MARKUP.sub("", raw)).strip()


class RateLimiter:
    """Global token bucket. Peapix is a small site; do not flood it."""

    def __init__(self, per_second):
        self._interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0

    def acquire(self):
        if not self._interval:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self._interval
        if wait > 0:
            time.sleep(wait)


class Session:
    """Thread-local keep-alive HTTPS connections.

    Enumerating ~35k pages over one-shot urllib connections means ~35k TLS
    handshakes; reusing a connection per worker thread removes essentially all
    of that cost.
    """

    def __init__(self, limiter):
        self._limiter = limiter
        self._local = threading.local()

    def _connection(self, host, fresh=False):
        pool = getattr(self._local, "pool", None)
        if pool is None:
            pool = self._local.pool = {}
        if fresh and host in pool:
            try:
                pool[host].close()
            except OSError:
                pass
            del pool[host]
        if host not in pool:
            pool[host] = http.client.HTTPSConnection(host, timeout=TIMEOUT)
        return pool[host]

    def get(self, host, path, byte_range=None, attempts=5):
        headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        if byte_range is not None:
            headers["Range"] = f"bytes=0-{byte_range}"
        last_error = None
        for attempt in range(attempts):
            self._limiter.acquire()
            try:
                connection = self._connection(host, fresh=attempt > 0)
                connection.request("GET", path, headers=headers)
                response = connection.getresponse()
                body = response.read()
                status = response.status
                if status == 404:
                    return 404, b""
                if status in (200, 206):
                    return status, body
                if status in (301, 302, 307, 308):
                    return status, b""
                last_error = f"HTTP {status}"
            except (http.client.HTTPException, OSError, TimeoutError) as error:
                last_error = error
                self._connection(host, fresh=True)
            time.sleep(min(30.0, 1.5 * (2**attempt)))
        raise RuntimeError(f"https://{host}{path}: {last_error}")


def jpeg_dimensions(data):
    """Read width/height from a JPEG SOF segment, tolerating a truncated file."""
    if not data.startswith(b"\xff\xd8"):
        return None
    index = 2
    end = len(data)
    while index + 3 < end:
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        if marker == 0xFF:
            index += 1
            continue
        if marker in STANDALONE_MARKERS:
            index += 2
            continue
        if index + 4 > end:
            return None
        length = int.from_bytes(data[index + 2 : index + 4], "big")
        if marker in SOF_MARKERS:
            if index + 9 > end:
                return None
            height = int.from_bytes(data[index + 5 : index + 7], "big")
            width = int.from_bytes(data[index + 7 : index + 9], "big")
            return width, height
        if length < 2:
            return None
        index += 2 + length
    return None


def perceptual_hash(path=None, data=None):
    """64-bit dhash as 16 hex chars.

    Row-wise adjacent-pixel comparison on a 9x8 greyscale reduction. Survives
    rescaling and requantisation, so the same photograph republished at a
    different size or quality collapses onto one value.
    """
    source = str(path) if path is not None else "-"
    result = subprocess.run(
        ["magick", source, "-colorspace", "Gray", "-resize", "9x8!", "-depth", "8", "GRAY:-"],
        input=data,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) != 72:
        return ""
    raw = result.stdout
    bits = 0
    for row in range(8):
        line = raw[row * 9 : (row + 1) * 9]
        for column in range(8):
            bits = (bits << 1) | (1 if line[column] < line[column + 1] else 0)
    return f"{bits:016x}"


def grayscale_signature(path=None, data=None):
    """64x64 greyscale reduction, used to confirm a suspected duplicate.

    A 64-bit dhash is far too coarse to act on alone: low-detail frames (night
    skies, flat water) collide with completely unrelated photographs. Measured
    on this collection, genuine duplicates score under 0.4 RMSE here while
    dhash false positives score above 6.
    """
    source = str(path) if path is not None else "-"
    result = subprocess.run(
        ["magick", source, "-colorspace", "Gray", "-resize", "64x64!", "-depth", "8", "GRAY:-"],
        input=data,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) != 4096:
        return None
    return result.stdout


SIGNATURE_DUPLICATE_RMSE = 3.0


def signatures_match(left, right):
    if not left or not right:
        return False
    total = sum((a - b) ** 2 for a, b in zip(left, right))
    return math.sqrt(total / len(left)) < SIGNATURE_DUPLICATE_RMSE


def image_size(path):
    """Dimensions of a local file, via ImageMagick so PNG and friends work too."""
    result = subprocess.run(
        ["magick", "identify", "-ping", "-format", "%w %h", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    parts = result.stdout.split()
    if result.returncode != 0 or len(parts) != 2:
        return None
    return int(parts[0]), int(parts[1])


def parse_page(page):
    """Extract metadata from a peapix detail page.

    The description sits between the headline and the tag list on both
    sections; bing has no ``position-relative`` wrapper around it, so the
    region is bounded by the surrounding landmarks instead.
    """
    key = KEY_PATTERN.search(page)
    if not key:
        return None

    country = COUNTRY_PATTERN.search(page)
    title = TITLE_PATTERN.search(page)
    copyright_notice = COPYRIGHT_PATTERN.search(page)
    headline = HEADLINE_PATTERN.search(page)
    date = DATE_PATTERN.search(page)
    tag_block = TAGS_PATTERN.search(page)

    body_start = headline.end() if headline else 0
    body_end = page.find('class="tag-list"', body_start)
    if body_end == -1:
        body_end = min(len(page), body_start + 12000)
    paragraphs = [clean(paragraph) for paragraph in PARAGRAPH_PATTERN.findall(page[body_start:body_end])]

    tags = [clean(tag) for tag in TAG_PATTERN.findall(tag_block.group(1))] if tag_block else []

    return {
        "key": key.group(1),
        "country": country.group(1) if country else "",
        "title": clean(title.group(1)) if title else "",
        "headline": clean(headline.group(1)) if headline else "",
        "description": "\n\n".join(paragraph for paragraph in paragraphs if paragraph),
        "copyright": clean(copyright_notice.group(1)) if copyright_notice else "",
        "date": date.group(1) if date else "",
        "tags": [tag for tag in tags if tag],
    }


class JsonlCache:
    """Append-only resume log. Rewriting a 40 MB index every checkpoint is the
    only part of a 35k-page crawl that would dominate its own runtime."""

    def __init__(self, path):
        self.path = path
        self.records = {}
        self._lock = threading.Lock()
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    self.records[record["k"]] = record["v"]
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8")

    def __contains__(self, key):
        return key in self.records

    def get(self, key, default=None):
        return self.records.get(key, default)

    def put(self, key, value):
        with self._lock:
            self.records[key] = value
            self._handle.write(json.dumps({"k": key, "v": value}, ensure_ascii=False) + "\n")
            self._handle.flush()

    def close(self):
        self._handle.close()


def load_metadata():
    try:
        stored = json.loads(METADATA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    stored.setdefault("version", 1)
    stored["source"] = "https://peapix.com"
    stored.setdefault("entries", {})
    return stored


def save_metadata(metadata):
    # Serialise a sorted *copy*. Rebinding metadata["entries"] here would
    # orphan the live dict that callers hold across checkpoints, silently
    # discarding everything written after the first save.
    payload = dict(metadata)
    payload["entries"] = dict(sorted(metadata["entries"].items()))
    temporary = METADATA_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    temporary.replace(METADATA_FILE)


def local_images():
    return sorted(
        path
        for path in WALLPAPER_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in EXTENSIONS
    )


def hash_existing(metadata, refresh, workers):
    """Give every file already on disk a sha256 and dhash.

    Without this the new downloads have nothing to deduplicate against, and the
    893 spotlight wallpapers already present would be re-fetched under bing ids
    whenever the two sections share a photograph.
    """
    import hashlib

    entries = metadata["entries"]
    pending = []
    for path in local_images():
        entry = entries.get(path.name, {})
        if not (refresh or not entry.get("sha256") or not entry.get("dhash") or not entry.get("width")):
            continue
        # Hashing a Git LFS stub would write the pointer's digest into metadata
        # and poison deduplication for every later run.
        if is_lfs_pointer(path):
            continue
        pending.append(path)
    if not pending:
        return
    print(f"hashing {len(pending)} existing images", file=sys.stderr)

    def work(path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return path.name, digest, perceptual_hash(path=path), image_size(path)

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for name, digest, fingerprint, size in pool.map(work, pending):
            entry = entries.setdefault(name, {})
            entry["sha256"] = digest
            entry["dhash"] = fingerprint
            if size:
                entry["width"], entry["height"] = size
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(pending)}", file=sys.stderr)
                save_metadata(metadata)
    save_metadata(metadata)


def discover(session, cache, section, start, stop, workers, recheck_missing=False):
    """Fetch every detail page in a section's id range into the resume cache.

    recheck_missing re-tries ids previously recorded as absent. An incremental
    run must do this: an id that 404s today is simply one peapix has not
    published yet, and without the retry the cache would permanently bury
    every wallpaper that lands on an id a previous run already looked at. The
    full backfill leaves it off, since re-fetching ten thousand known 404s
    every time would be pointless.
    """
    pending = [
        identifier
        for identifier in range(start, stop)
        if f"{section}/{identifier}" not in cache
        or (recheck_missing and cache.get(f"{section}/{identifier}") is None)
    ]
    print(
        f"{section}: {stop - start} ids in range, {len(pending)} to fetch",
        file=sys.stderr,
    )
    if not pending:
        return

    def work(identifier):
        status, body = session.get(SITE_HOST, f"/{section}/{identifier}")
        if status != 200:
            return identifier, None
        return identifier, parse_page(body.decode("utf-8", "replace"))

    done = 0
    found = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for identifier, record in pool.map(work, pending):
            cache.put(f"{section}/{identifier}", record)
            done += 1
            found += record is not None
            if done % 500 == 0:
                print(f"  {section} {done}/{len(pending)} ({found} pages)", file=sys.stderr)
    print(f"  {section} done: {found} pages exist", file=sys.stderr)


# Every market peapix publishes bing under. Used by the incremental scan to
# find the newest id without enumerating the whole archive.
MARKETS = ["au", "br", "ca", "cn", "de", "es", "fr", "gb", "in", "it", "jp", "us"]

# Bing republishes each image per market with localised text. Ranked so the
# canonical record carries English prose rather than whichever market happened
# to get the lowest id.
ENGLISH_MARKETS = ["us", "gb", "au", "ca", "in"]
MARKET_RANK = {market: index for index, market in enumerate(ENGLISH_MARKETS)}


def canonical_rank(section, record, identifier):
    """Sort key deciding which of an image's ids names the file on disk.

    Spotlight first (it is the existing naming scheme and always English), then
    English bing markets, then everything else. Id breaks ties so the choice is
    stable across reruns.
    """
    if section == "spotlight":
        return (0, 0, identifier)
    return (1, MARKET_RANK.get(record.get("country", ""), len(ENGLISH_MARKETS)), identifier)


def newest_published_id(session, section):
    """Highest page id peapix currently serves in a section.

    The JSON feeds ignore their date parameters, so they are useless for
    backfilling, but they do report the newest handful of pages. That is
    exactly what an incremental run needs, and it costs 1 request for
    spotlight or 12 for bing instead of enumerating tens of thousands of ids.
    """
    paths = (
        ["/spotlight/feed"]
        if section == "spotlight"
        else [f"/bing/feed?country={market}" for market in MARKETS]
    )
    highest = 0
    for path in paths:
        try:
            status, body = session.get(SITE_HOST, path)
        except RuntimeError as error:
            print(f"  feed {path} failed: {error}", file=sys.stderr)
            continue
        if status != 200:
            continue
        try:
            items = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            continue
        for item in items:
            match = re.search(r"/(\d+)\s*$", str(item.get("pageUrl", "")))
            if match:
                highest = max(highest, int(match.group(1)))
    return highest


def highest_known_id(metadata, section):
    """Newest id already recorded, counting the per-market aliases."""
    best = 0
    for entry in metadata["entries"].values():
        if entry.get("source") == section:
            identifier = str(entry.get("id", ""))
            if identifier.isdigit():
                best = max(best, int(identifier))
        for alias in entry.get("aliases", []):
            alias_section, _, raw = str(alias).partition("/")
            if alias_section == section and raw.isdigit():
                best = max(best, int(raw))
    return best


def incremental_range(session, metadata, section, margin):
    """Id window to scan for new publications, or None when already current."""
    known = highest_known_id(metadata, section)
    if not known:
        return None
    newest = newest_published_id(session, section)
    if not newest or newest <= known:
        print(f"{section}: up to date at id {known}", file=sys.stderr)
        return None
    # The margin re-checks ids just below the known high-water mark, because a
    # market can publish slightly out of order and a strict cut would skip it.
    return max(1, known - margin + 1), newest + 1


def group_by_key(cache, sections):
    """Collapse the per-market id explosion onto one record per image.

    Non-canonical ids are kept as aliases, which is what lets an incremental
    run recognise an image it already holds under a different market's id.
    """
    collected = {}
    for page_key, record in cache.records.items():
        if not record:
            continue
        section, _, raw_identifier = page_key.partition("/")
        if section not in sections:
            continue
        collected.setdefault(record["key"], []).append((section, int(raw_identifier), record))

    groups = {}
    for key, pages in collected.items():
        pages.sort(key=lambda page: canonical_rank(page[0], page[2], page[1]))
        section, identifier, record = pages[0]
        groups[key] = {
            "record": record,
            "section": section,
            "id": identifier,
            "country": record.get("country", ""),
            "aliases": sorted(f"{other[0]}/{other[1]}" for other in pages[1:]),
        }
    return groups


def probe_dimensions(session, cache, keys, workers):
    """Read native size from each image's JPEG header via a ranged GET."""
    # A cached null means "could not determine", not "known small", so those
    # are retried instead of being written off permanently.
    pending = [key for key in keys if cache.get(key) is None]
    print(f"probing {len(pending)} image headers", file=sys.stderr)
    if not pending:
        return

    def work(key):
        for byte_range in HEADER_PROBE_SIZES:
            status, body = session.get(IMAGE_HOST, f"/{key}.jpg", byte_range=byte_range)
            if status not in (200, 206):
                return key, None
            dimensions = jpeg_dimensions(body)
            if dimensions:
                return key, dimensions
            if len(body) <= (byte_range or 0):
                # Whole file already seen; a missing SOF means it is not a
                # JPEG we can read, so escalating further would not help.
                break
        return key, None

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for key, dimensions in pool.map(work, pending):
            cache.put(key, list(dimensions) if dimensions else None)
            done += 1
            if done % 250 == 0:
                print(f"  {done}/{len(pending)}", file=sys.stderr)


LFS_POINTER_PREFIX = b"version https://git-lfs"


def is_lfs_pointer(path):
    """True when a checkout left a Git LFS stub instead of the real image."""
    try:
        with path.open("rb") as handle:
            return handle.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX
    except OSError:
        return False


def materialise(path):
    """Fetch one image's real bytes when only its LFS pointer is checked out.

    CI clones with lfs disabled, because deduplication runs off the hashes in
    metadata.json and pulling 17 GB of pixels to add three wallpapers would be
    absurd. The pixel confirmation below is the one place that still needs a
    stored image, and it is reached for roughly one download in four hundred.
    """
    if not is_lfs_pointer(path):
        return True
    result = subprocess.run(
        ["git", "-C", str(WALLPAPER_DIR), "lfs", "pull", "--include", path.name],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and not is_lfs_pointer(path)


def resolve_duplicate(by_sha, by_dhash, result, name):
    """Name of the stored wallpaper this download duplicates, or None.

    Identical bytes settle it outright. A dhash hit is only a candidate and
    must be confirmed against the stored file's pixels, because dhash alone
    rejected 7 genuinely distinct images out of 11 candidates here.
    """
    exact = by_sha.get(result["sha256"])
    if exact:
        return exact
    candidate = by_dhash.get(result["dhash"]) if result["dhash"] else None
    if not candidate:
        return None
    stored = WALLPAPER_DIR / candidate
    if not stored.exists() or not materialise(stored):
        # Never discard an image we cannot actually compare. Keeping a possible
        # duplicate is recoverable; deleting a distinct wallpaper is not.
        print(
            f"  keeping {name}: dhash matches {candidate}, which is unavailable to compare",
            file=sys.stderr,
        )
        result["needsDuplicateReview"] = candidate
        return None
    if signatures_match(
        grayscale_signature(path=stored), grayscale_signature(data=result["body"])
    ):
        return candidate
    print(
        f"  keeping {name}: dhash matches {candidate} but pixels differ",
        file=sys.stderr,
    )
    return None


def download(session, metadata, targets, workers, limit):
    import hashlib

    entries = metadata["entries"]
    by_sha = {}
    by_dhash = {}
    for name, entry in entries.items():
        if entry.get("sha256"):
            by_sha.setdefault(entry["sha256"], name)
        if entry.get("dhash"):
            by_dhash.setdefault(entry["dhash"], name)

    if limit:
        targets = targets[:limit]
    print(f"downloading {len(targets)} images", file=sys.stderr)

    lock = threading.Lock()
    counters = {"saved": 0, "duplicate": 0, "failed": 0, "done": 0}

    def work(target):
        key = target["key"]
        status, body = session.get(IMAGE_HOST, f"/{key}.jpg")
        if status != 200 or not body:
            return target, None, "fetch failed"
        dimensions = jpeg_dimensions(body)
        if not dimensions or dimensions[0] < MINIMUM_WIDTH or dimensions[1] < MINIMUM_HEIGHT:
            return target, None, f"not 4K ({dimensions})"
        return (
            target,
            {
                "body": body,
                "width": dimensions[0],
                "height": dimensions[1],
                "sha256": hashlib.sha256(body).hexdigest(),
                "dhash": perceptual_hash(data=body),
            },
            None,
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for target, result, reason in pool.map(work, targets):
            with lock:
                counters["done"] += 1
                if result is None:
                    counters["failed"] += 1
                    print(f"  skip {target['name']}: {reason}", file=sys.stderr)
                elif duplicate := resolve_duplicate(by_sha, by_dhash, result, target["name"]):
                    # The bytes were discarded, so the stored file keeps its own
                    # hashes and size. Only record that this peapix id is
                    # another name for an image already held.
                    counters["duplicate"] += 1
                    entry = entries.setdefault(duplicate, {})
                    extra = {f"{target['section']}/{target['id']}", *target["aliases"]}
                    entry["aliases"] = sorted(set(entry.get("aliases", [])) | extra)
                    # Remember the rejected image key as well, otherwise the
                    # next run has no record that it was already considered and
                    # re-downloads the same bytes to discard them again.
                    entry["duplicateKeys"] = sorted(
                        set(entry.get("duplicateKeys", [])) | {target["key"]}
                    )
                else:
                    path = WALLPAPER_DIR / target["name"]
                    temporary = path.with_suffix(".part")
                    temporary.write_bytes(result["body"])
                    temporary.replace(path)
                    by_sha[result["sha256"]] = target["name"]
                    if result["dhash"]:
                        by_dhash[result["dhash"]] = target["name"]
                    counters["saved"] += 1

                    record = target["record"]
                    entry = entries.setdefault(target["name"], {})
                    entry.update(
                        {
                            "title": record["title"],
                            "headline": record["headline"],
                            "description": record["description"],
                            "copyright": record["copyright"],
                            "date": record["date"],
                            "tags": record["tags"],
                            "id": str(target["id"]),
                            "url": f"https://{SITE_HOST}/{target['section']}/{target['id']}",
                            "source": target["section"],
                            "market": record.get("country", ""),
                            "imageKey": record["key"],
                            "width": result["width"],
                            "height": result["height"],
                            "sha256": result["sha256"],
                            "dhash": result["dhash"],
                        }
                    )
                    if result.get("needsDuplicateReview"):
                        entry["needsDuplicateReview"] = result["needsDuplicateReview"]
                    if target["aliases"]:
                        merged = set(entry.get("aliases", [])) | set(target["aliases"])
                        entry["aliases"] = sorted(merged)

                if counters["done"] % 50 == 0:
                    print(
                        f"  {counters['done']}/{len(targets)} "
                        f"saved={counters['saved']} dup={counters['duplicate']} "
                        f"failed={counters['failed']}",
                        file=sys.stderr,
                    )
                    save_metadata(metadata)

    save_metadata(metadata)
    print(
        f"saved {counters['saved']}, duplicates {counters['duplicate']}, "
        f"failed {counters['failed']}",
        file=sys.stderr,
    )


def backfill_known(metadata, groups, dimensions=None):
    """Attach peapix fields to files already on disk under a known name.

    This is also the repair path: a file whose bytes were fetched but whose
    metadata never landed is restored from the discovery cache on the next
    run, with no refetching.
    """
    entries = metadata["entries"]
    present = {path.name for path in local_images()}
    held_by_key = {
        entry["imageKey"]: name
        for name, entry in entries.items()
        if entry.get("imageKey") and name in present
    }
    updated = 0
    aliased = 0
    for key, group in groups.items():
        name = NAME_TEMPLATES[group["section"]].format(identifier=group["id"])
        if name not in present:
            # A later market republication can outrank the market this image
            # was first stored under, moving the canonical name to a file that
            # does not exist. The image is already held under the old name, so
            # only fold the newly seen ids into its aliases instead of
            # renaming it.
            stored = held_by_key.get(key)
            if stored:
                known = set(entries[stored].get("aliases", []))
                seen = {f"{group['section']}/{group['id']}", *group["aliases"]}
                seen.discard(f"{entries[stored].get('source')}/{entries[stored].get('id')}")
                if not seen <= known:
                    entries[stored]["aliases"] = sorted(known | seen)
                    aliased += 1
            continue
        record = group["record"]
        entry = entries.setdefault(name, {})
        size = dimensions.get(key) if dimensions else None
        if size:
            entry["width"], entry["height"] = size[0], size[1]
        entry.update(
            {
                "title": record["title"],
                "headline": record["headline"],
                "description": record["description"],
                "copyright": record["copyright"],
                "date": record["date"],
                "tags": record["tags"],
                "id": str(group["id"]),
                "url": f"https://{SITE_HOST}/{group['section']}/{group['id']}",
                "source": group["section"],
                "market": group.get("country", ""),
                "imageKey": key,
            }
        )
        if group["aliases"]:
            entry["aliases"] = sorted(set(entry.get("aliases", [])) | set(group["aliases"]))
        updated += 1
    if updated or aliased:
        print(
            f"backfilled peapix fields on {updated} existing files"
            + (f", refreshed aliases on {aliased}" if aliased else ""),
            file=sys.stderr,
        )
        save_metadata(metadata)


def report_near_duplicates(metadata, distance):
    """dhash collisions are auto-skipped; near misses only get reported, since
    a low distance can also mean two genuinely different but flat images."""
    entries = [
        (name, int(entry["dhash"], 16))
        for name, entry in metadata["entries"].items()
        if entry.get("dhash")
    ]

    # Pigeonhole multi-index: split the 64 bits into distance+1 disjoint
    # blocks. Two hashes differing in at most `distance` bits must agree
    # exactly on at least one block, so candidates can be found by equality
    # instead of comparing all ~10M pairs.
    blocks = max(1, distance + 1)
    bounds = [(index * 64 // blocks, (index + 1) * 64 // blocks) for index in range(blocks)]
    indexes = [{} for _ in bounds]
    for name, fingerprint in entries:
        for position, (low, high) in enumerate(bounds):
            segment = (fingerprint >> low) & ((1 << (high - low)) - 1)
            indexes[position].setdefault(segment, []).append((name, fingerprint))

    pairs = set()
    for name, fingerprint in entries:
        for position, (low, high) in enumerate(bounds):
            segment = (fingerprint >> low) & ((1 << (high - low)) - 1)
            for other_name, other in indexes[position].get(segment, ()):
                if name < other_name and 0 < (fingerprint ^ other).bit_count() <= distance:
                    pairs.add((name, other_name))

    if pairs:
        print(f"{len(pairs)} near-duplicate pairs (dhash distance <= {distance}):", file=sys.stderr)
        for left, right in sorted(pairs)[:40]:
            print(f"  {left}  ~  {right}", file=sys.stderr)


def parse_range(text):
    start, _, stop = text.partition(":")
    return int(start), int(stop)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sections", default="spotlight,bing")
    parser.add_argument("--bing-range", default="36000:57800", type=parse_range)
    parser.add_argument("--spotlight-range", default="1:12800", type=parse_range)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--download-workers", type=int, default=4)
    parser.add_argument("--rate", type=float, default=20.0, help="max requests per second")
    parser.add_argument("--limit", type=int, default=0, help="cap downloads (for testing)")
    parser.add_argument("--rehash", action="store_true", help="recompute hashes for local files")
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="scan only ids newer than what metadata.json already records",
    )
    parser.add_argument("--incremental-margin", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--near-duplicate-distance", type=int, default=3)
    arguments = parser.parse_args()

    sections = [section for section in arguments.sections.split(",") if section]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WALLPAPER_DIR.mkdir(parents=True, exist_ok=True)

    session = Session(RateLimiter(arguments.rate))
    metadata = load_metadata()
    hash_existing(metadata, arguments.rehash, arguments.workers)

    pages = JsonlCache(PAGES_CACHE)
    ranges = {"bing": arguments.bing_range, "spotlight": arguments.spotlight_range}
    for section in sections:
        if arguments.incremental:
            window = incremental_range(
                session, metadata, section, arguments.incremental_margin
            )
            if window is None:
                continue
            start, stop = window
            print(f"{section}: incremental scan {start}..{stop - 1}", file=sys.stderr)
        else:
            start, stop = ranges[section]
        discover(
            session,
            pages,
            section,
            start,
            stop,
            arguments.workers,
            recheck_missing=arguments.incremental,
        )

    groups = group_by_key(pages, set(sections))
    print(f"{len(groups)} distinct images across {len(sections)} sections", file=sys.stderr)

    if arguments.discover_only:
        backfill_known(metadata, groups)
        pages.close()
        return

    dimensions = JsonlCache(DIMENSIONS_CACHE)
    probe_dimensions(session, dimensions, list(groups), arguments.workers)
    backfill_known(metadata, groups, dimensions)

    present = {path.name for path in local_images()}
    known_keys = set()
    for name, entry in metadata["entries"].items():
        if name not in present:
            continue
        if entry.get("imageKey"):
            known_keys.add(entry["imageKey"])
        known_keys.update(entry.get("duplicateKeys", []))

    targets = []
    undersized = 0
    for key, group in sorted(groups.items(), key=lambda item: -item[1]["id"]):
        size = dimensions.get(key)
        if not size or size[0] < MINIMUM_WIDTH or size[1] < MINIMUM_HEIGHT:
            undersized += 1
            continue
        name = NAME_TEMPLATES[group["section"]].format(identifier=group["id"])
        if name in present or key in known_keys:
            continue
        targets.append({"key": key, "name": name, **group})

    print(
        f"{undersized} below {MINIMUM_WIDTH}x{MINIMUM_HEIGHT}, {len(targets)} to download",
        file=sys.stderr,
    )

    if arguments.dry_run:
        for target in targets[:20]:
            print(f"  would fetch {target['name']} <- {target['key']}", file=sys.stderr)
    else:
        download(session, metadata, targets, arguments.download_workers, arguments.limit)
        report_near_duplicates(metadata, arguments.near_duplicate_distance)

    pages.close()
    dimensions.close()


if __name__ == "__main__":
    main()
