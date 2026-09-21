#!/usr/bin/env python3
"""Add English text to the bing wallpapers that were only ever published abroad.

Bing runs a separate image on many days per market, so 1100-odd wallpapers in
~/Wallpapers exist solely with German, French, Japanese, Spanish, Italian,
Portuguese or Chinese prose. There is no English edition on peapix to prefer -
that was checked - so the only way to make them searchable is to translate.

Originals are never overwritten. The translation lands in englishTitle /
englishHeadline / englishDescription, and the picker falls back to the
original whenever those are absent.
"""

import argparse
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import palette

# Markets whose pages are already English; everything else needs translating.
ENGLISH_MARKETS = {"us", "gb", "au", "ca", "in"}

# Derived from the market rather than left to auto-detection: the source
# language is known exactly, and a wrong guess on a short title is expensive.
LANGUAGE_BY_MARKET = {
    "br": "pt",
    "cn": "zh-CN",
    "de": "de",
    "es": "es",
    "fr": "fr",
    "it": "it",
    "jp": "ja",
}

TRANSLATED_FIELDS = [
    ("title", "englishTitle"),
    ("headline", "englishHeadline"),
    ("description", "englishDescription"),
]


# translate-shell exits 0 even when the backend refuses, writing the reason to
# stderr, so rate limiting has to be recognised by text.
RATE_LIMIT_MARKERS = ("rate limit", "too many requests", "429", "503")
# Google's limiter works on a window of minutes; retrying after a second or two
# just burns through the rest of the queue failing.
RATE_LIMIT_BACKOFF = [30, 60, 120, 240]


class EnginePool:
    """Paces requests and sidelines engines that start refusing.

    Cooldowns are per engine and shared by every worker. Google gives the best
    prose but throttles an address for a long time once provoked; Bing is
    unaffected by that and takes over automatically, so a run finishes instead
    of stalling on a backend that has stopped answering.
    """

    def __init__(self, engines, per_second):
        self._engines = list(engines)
        self._interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = threading.Lock()
        self._next = 0.0
        self._cooldown = dict.fromkeys(self._engines, 0.0)

    def ready_engines(self):
        """Engines usable now, else how long until the first one recovers."""
        with self._lock:
            now = time.monotonic()
            ready = [engine for engine in self._engines if self._cooldown[engine] <= now]
            if ready:
                return ready, 0.0
            return [], max(0.0, min(self._cooldown.values()) - now)

    def pace(self):
        if not self._interval:
            return
        with self._lock:
            now = time.monotonic()
            wait = self._next - now
            self._next = max(now, self._next) + self._interval
        if wait > 0:
            time.sleep(wait)

    def penalise(self, engine, seconds):
        with self._lock:
            self._cooldown[engine] = max(
                self._cooldown.get(engine, 0.0), time.monotonic() + seconds
            )

    def penalties(self):
        with self._lock:
            now = time.monotonic()
            return {
                engine: round(until - now)
                for engine, until in self._cooldown.items()
                if until > now
            }


def translate(pool, text, source, attempts=6):
    """Translate one field, preserving its blank-line paragraph breaks.

    Text goes through a temporary file rather than argv: descriptions run to
    2400 characters and contain newlines, quotes and non-ASCII throughout.
    A refusal leaves stdout empty, so a failed call can never be mistaken for
    a translation and written into metadata.
    """
    text = (text or "").strip()
    if not text:
        return ""
    for attempt in range(attempts):
        engines, wait = pool.ready_engines()
        if not engines:
            time.sleep(min(wait, 15.0))
            continue

        for engine in engines:
            pool.pace()
            with tempfile.NamedTemporaryFile(
                "w", suffix=".txt", encoding="utf-8", delete=True
            ) as handle:
                handle.write(text)
                handle.flush()
                result = subprocess.run(
                    ["trans", "-e", engine, "-b", "-s", source, "-t", "en", "-i", handle.name],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            translated = result.stdout.strip()
            if translated:
                return translated

            stderr = (result.stderr or "").lower()
            if any(marker in stderr for marker in RATE_LIMIT_MARKERS):
                delay = RATE_LIMIT_BACKOFF[min(attempt, len(RATE_LIMIT_BACKOFF) - 1)]
                print(f"  {engine} rate limited, sidelining {delay}s", file=sys.stderr)
                pool.penalise(engine, delay)
            else:
                # A transient failure, not a refusal: briefly park this engine
                # so the next attempt tries the other one first.
                pool.penalise(engine, 5)
    return ""


def pending_entries(entries, refresh):
    targets = []
    for name, entry in sorted(entries.items()):
        if entry.get("source") != "bing":
            continue
        market = entry.get("market", "")
        if market in ENGLISH_MARKETS or market not in LANGUAGE_BY_MARKET:
            continue
        if not refresh and all(
            entry.get(target) or not entry.get(source) for source, target in TRANSLATED_FIELDS
        ):
            continue
        targets.append((name, entry, LANGUAGE_BY_MARKET[market]))
    return targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    # Measured: 4 workers at 6/s tripped Google's limiter after ~400 wallpapers.
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--rate", type=float, default=2.5, help="max requests per second")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--refresh", action="store_true", help="retranslate everything")
    parser.add_argument(
        "--engines",
        default="google,bing",
        help="translation backends to try, in order of preference",
    )
    arguments = parser.parse_args()

    metadata = palette.load_metadata()
    entries = metadata["entries"]
    targets = pending_entries(entries, arguments.refresh)
    if arguments.limit:
        targets = targets[: arguments.limit]

    print(f"{len(targets)} wallpapers to translate", file=sys.stderr)
    if not targets:
        return

    engines = [engine for engine in arguments.engines.split(",") if engine]
    backends = EnginePool(engines, arguments.rate)
    lock = threading.Lock()
    counters = {"done": 0, "failed": 0}

    def work(target):
        name, entry, source = target
        translated = {}
        for field, destination in TRANSLATED_FIELDS:
            original = entry.get(field, "")
            if not original:
                continue
            if not arguments.refresh and entry.get(destination):
                continue
            rendered = translate(backends, original, source)
            if rendered:
                translated[destination] = rendered
        return name, translated

    with ThreadPoolExecutor(max_workers=arguments.workers) as pool:
        for name, translated in pool.map(work, targets):
            with lock:
                counters["done"] += 1
                if translated:
                    entries[name].update(translated)
                else:
                    counters["failed"] += 1
                    print(f"  no translation for {name}", file=sys.stderr)
                if counters["done"] % 25 == 0:
                    print(f"  {counters['done']}/{len(targets)}", file=sys.stderr)
                    palette.save_metadata(metadata)

    palette.save_metadata(metadata)
    print(
        f"translated {counters['done'] - counters['failed']} wallpapers, {counters['failed']} failed",
        file=sys.stderr,
    )
    sidelined = backends.penalties()
    if sidelined:
        print(f"engines still cooling down: {sidelined}", file=sys.stderr)


if __name__ == "__main__":
    main()
