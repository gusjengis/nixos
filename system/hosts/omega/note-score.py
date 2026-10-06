"""Rank open thoughts with Jev (TypeSafe's System One model) against Facets.md.

Composite scoring: for each open thought, one Jev request asks a Score
question per facet ("how much does this advance <aim>?") plus urgency, effort,
unblocks and a comparison with the thought's linked neighbors. Code combines
the answers with the weights in Facets.md and writes `score` (a float, higher
is more important) into the thought's frontmatter.

The state sent to Jev is small on purpose (Jev loses accuracy on irrelevant
context): the thought itself, the titles and first lines of the thoughts it
links to, and the names of entities it mentions. Dates, counts and link
popularity are never asked of the model.

Answers are cached by request content, so a run only calls the API for
thoughts whose text, neighbors or facet aims changed; changing a weight
re-ranks everything for free. A file is rewritten only when its score fields
change, to keep Obsidian Sync quiet.

Fields written (pipeline-owned; see notes/DATA_MODEL.md):
  score         float, the final rank key
  score-facet   the facet that contributes most
  score-parts   human-readable breakdown
  score-unsure  true when Jev was split on the facet or urgency rating
"""

import argparse
import concurrent.futures
import datetime
import fcntl
import hashlib
import importlib.util
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.typesafe.ai/v1/systemone"
FIELDS = ("score", "score-facet", "score-parts", "score-unsure")

# Thoughts that can be acted on or resolved; insights, logs, reflections,
# values and quotes are context, not work.
SCORED_TYPES = {
    "task", "reminder", "purchase", "person-action", "idea", "project",
    "question", "decision", "goal", "resource",
}
CLOSED = {"done", "dropped"}

DEFAULT_MIX = {
    "impact": 0.55, "urgency": 0.25, "quick": 0.10, "unblocks": 0.10,
    "local": 0.10, "secondary": 0.2, "priority-boost": 0.15, "blocks-boost": 0.03,
}
UNSURE_BELOW = 0.35
MAX_NEIGHBORS = 12

# Level descriptions describe situations, not degrees: Jev judges each level
# on its own and never sees its number.
FACET_LEVELS = [
    "Unrelated to `aim`: finishing `thought` would not change progress on it at all",
    "Loosely related to `aim`: at most a minor or indirect contribution",
    "A real but small step toward `aim`",
    "A significant step toward `aim`",
    "A major, direct step toward `aim`; one of the most important things for it",
]
FIXED_QUESTIONS = {
    "urgency": {
        "type": "score",
        "instructions": "How time-sensitive is `thought`, judging only from what it says?",
        "criteria": [
            "No time pressure; it could wait months without any loss",
            "Nice to do soon, but waiting costs little",
            "Should happen within a few weeks; waiting has a real cost",
            "Should happen this week: a deadline, appointment, or a cost that grows daily",
            "Must happen today; otherwise something breaks, is missed, or is lost",
        ],
    },
    "effort": {
        "type": "score",
        "instructions": "How much work is the next concrete step of `thought`?",
        "criteria": [
            "Minutes: a quick message, purchase, lookup, or check",
            "Under an hour of focused work",
            "A few hours, or one long sitting",
            "Several days of work",
            "Weeks or more, or too vague to know what the next step is",
        ],
    },
    "unblocks": {
        "type": "score",
        "instructions": "How much other work is waiting on `thought` being finished, judging from `thought` and `neighbors`?",
        "criteria": [
            "Nothing is waiting on it",
            "It makes one other thing somewhat easier",
            "It directly unblocks another specific task",
            "It unblocks several tasks or a whole project",
        ],
    },
}
LOCAL_QUESTION = {
    "type": "score",
    "instructions": "Compared with the thoughts in `neighbors`, how important is `thought` for the person who wrote them?",
    "criteria": [
        "Clearly less important than most of `neighbors`",
        "Somewhat less important than most of `neighbors`",
        "About as important as `neighbors`",
        "Somewhat more important than most of `neighbors`",
        "Clearly more important than all of `neighbors`",
    ],
}


def load_extract(path: Path):
    """note-extract.py, for its frontmatter helpers: same YAML layout, same
    atomic writes, same Store, so a scored file round-trips byte-identically."""
    spec = importlib.util.spec_from_file_location("note_extract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- facets -----------------------------------------------------------------

def parse_facets(path: Path) -> tuple[list[dict], dict]:
    facets, mix, section = [], dict(DEFAULT_MIX), None
    fields: dict[str, str] = {}

    def close():
        if section is None:
            return
        if section.lower() == "mix":
            for key, value in fields.items():
                try:
                    mix[key] = float(value)
                except ValueError:
                    print(f"Facets: mix {key}:: {value!r} is not a number", flush=True)
        elif "aim" in fields and "weight" in fields:
            facets.append({
                "name": section,
                "id": re.sub(r"[^a-z0-9]+", "_", section.lower()).strip("_"),
                "weight": float(fields["weight"]),
                "aim": fields["aim"],
            })

    for line in path.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            close()
            section, fields = heading.group(1), {}
            continue
        field = re.match(r"^([A-Za-z][\w-]*)::\s*(.+?)\s*$", line)
        if field and section is not None:
            fields[field.group(1).lower()] = field.group(2)
    close()
    if not facets:
        sys.exit(f"{path}: no facets (need '## Name', 'weight::' and 'aim::')")
    return facets, mix


# --- requests ---------------------------------------------------------------

def first_line(ex, body: str, limit: int = 200) -> str:
    text = ex.thought_text(body).replace("\n", " ")
    return text[:limit]


def eligible(ex, meta: dict) -> bool:
    return (
        ex.visible(meta)
        and str(meta.get("status") or "").lower() not in CLOSED
        and bool(set(map(str, ex.as_list(meta.get("types")))) & SCORED_TYPES)
    )


def build_request(ex, store, rel: str, facets: list[dict], model: str) -> dict:
    meta, body = store.notes[rel]
    neighbors = []
    for key in ex.ORDER:
        if key not in ex.RELATION_KEYS or key in ("mentions", "mentioned-by", "source"):
            continue
        for other in ex.targets(meta, key):
            if not other.startswith("Thoughts/") or other not in store.notes:
                continue
            other_meta, other_body = store.notes[other]
            neighbors.append({
                # Spelled out from the thought's side: "thought blocks this".
                "relation": f"`thought` {key.replace('-', ' ')} this",
                "title": other.split("/", 1)[1],
                "status": other_meta.get("status") or "",
                "text": first_line(ex, other_body),
            })
    neighbors = neighbors[:MAX_NEIGHBORS]
    state = {
        "thought": {
            "title": rel.split("/", 1)[1],
            "types": list(map(str, ex.as_list(meta.get("types")))),
            "text": ex.thought_text(body),
            "mentions": [t.split("/", 1)[1] for t in ex.targets(meta, "mentions")],
        },
        "neighbors": neighbors,
    }
    questions = {}
    for facet in facets:
        questions[f"facet_{facet['id']}"] = {
            "type": "score",
            "instructions": {
                "aim": facet["aim"],
                "question": "How much would finishing or resolving `thought` advance `aim`?",
            },
            "criteria": FACET_LEVELS,
        }
    questions.update(FIXED_QUESTIONS)
    if neighbors:
        questions["local"] = LOCAL_QUESTION
    return {"model": model, "state": state, "questions": questions}


def request_key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def call_jev(payload: dict, key: str, attempts: int = 6) -> dict:
    data = json.dumps(payload).encode()
    delay = 2.0
    for attempt in range(attempts):
        request = urllib.request.Request(API, data=data, headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504, 529) or attempt == attempts - 1:
                detail = exc.read().decode(errors="replace")[:500]
                raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
            wait = float(exc.headers.get("retry-after") or delay)
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError(f"network: {exc}") from None
            wait = delay
        time.sleep(wait)
        delay = min(delay * 2, 60)
    raise AssertionError("unreachable")


# --- combine ----------------------------------------------------------------

def normalized(payload: dict, answers: dict, qid: str) -> tuple[float, float]:
    top = len(payload["questions"][qid]["criteria"]) - 1
    answer = answers[qid]
    return answer["score"] / top, answer.get("confidence", 1.0)


def combine(ex, store, rel: str, payload: dict, answers: dict, facets: list[dict], mix: dict) -> dict:
    meta = store.notes[rel][0]
    contributions = []
    for facet in facets:
        value, confidence = normalized(payload, answers, f"facet_{facet['id']}")
        contributions.append((facet["weight"] * value, value, confidence, facet))
    contributions.sort(key=lambda c: -c[0])
    best = contributions[0]
    rest = sum(c[0] for c in contributions[1:])
    impact = min(1.0, best[0] + mix["secondary"] * rest)

    urgency, urgency_conf = normalized(payload, answers, "urgency")
    effort, _ = normalized(payload, answers, "effort")
    unblocks, _ = normalized(payload, answers, "unblocks")
    local = normalized(payload, answers, "local")[0] if "local" in answers else 0.5
    quick = 1.0 - effort

    score = (
        mix["impact"] * impact + mix["urgency"] * urgency + mix["quick"] * quick
        + mix["unblocks"] * unblocks + mix["local"] * local
    )
    priority = str(meta.get("priority") or "normal").lower()
    if priority == "high":
        score += mix["priority-boost"]
    elif priority == "low":
        score -= mix["priority-boost"]
    blocked = [
        t for t in ex.targets(meta, "blocks")
        if t in store.notes and str(store.notes[t][0].get("status") or "").lower() not in CLOSED
    ]
    score += mix["blocks-boost"] * min(len(blocked), 3)

    others = ", ".join(
        f"{re.match(r'\w+', c[3]['name']).group(0).lower()} {c[1]:.2f}"
        for c in contributions[1:] if c[1] >= 0.25
    )
    parts = (
        f"impact {impact:.2f} ({best[3]['name']} {best[1]:.2f}"
        + (f"; {others}" if others else "")
        + f") · urgency {urgency:.2f} · quick {quick:.2f} · unblocks {unblocks:.2f}"
        + (f" · local {local:.2f}" if "local" in answers else "")
        + (f" · priority {priority}" if priority != "normal" else "")
        + (f" · blocks {len(blocked)}" if blocked else "")
    )
    fields = {
        "score": round(score, 3),
        "score-facet": best[3]["name"],
        "score-parts": parts,
    }
    if min(best[2], urgency_conf) < UNSURE_BELOW:
        fields["score-unsure"] = True
    return fields


# --- run --------------------------------------------------------------------

def open_cache(state: Path) -> sqlite3.Connection:
    state.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(state / "score.sqlite")
    db.execute("create table if not exists answers (key text primary key, response text, at text)")
    db.execute("create table if not exists runs (at text, calls int, tokens int, written int)")
    return db


def apply_fields(meta: dict, fields: dict | None) -> None:
    for key in FIELDS:
        meta.pop(key, None)
    if fields:
        meta.update(fields)


def run(args) -> None:
    ex = load_extract(args.extract_module)
    facets, mix = parse_facets(args.vault / "Facets.md")
    store = ex.Store(args.vault, dry_run=args.dry_run)
    thoughts = sorted(rel for rel in store.folder("Thoughts"))
    wanted = {f"Thoughts/{n.removeprefix('Thoughts/').removesuffix('.md')}" for n in args.notes}
    targets = [
        rel for rel in thoughts
        if eligible(ex, store.meta(rel)) and (not wanted or rel in wanted)
    ]
    payloads = {rel: build_request(ex, store, rel, facets, args.model) for rel in targets}

    if args.dry_run:
        for rel in targets[: args.limit]:
            print(json.dumps(payloads[rel], indent=2, ensure_ascii=False))
        print(f"{len(targets)} thought(s) eligible; {len(facets)} facets; mix {mix}", file=sys.stderr)
        return

    db = open_cache(args.state)
    cached = {}
    for rel, payload in payloads.items():
        row = db.execute("select response from answers where key = ?", (request_key(payload),)).fetchone()
        if row:
            cached[rel] = json.loads(row[0])
    missing = [rel for rel in targets if rel not in cached]

    tokens = 0
    if missing:
        key = args.key_file.read_text(encoding="utf-8").strip()
        print(f"asking Jev about {len(missing)} thought(s) ({len(targets) - len(missing)} cached)", flush=True)
        with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
            futures = {pool.submit(call_jev, payloads[rel], key): rel for rel in missing}
            for future in concurrent.futures.as_completed(futures):
                rel = futures[future]
                try:
                    response = future.result()
                except Exception as exc:  # one failure must not block the rest
                    print(f"  {rel}: {exc}", flush=True)
                    continue
                cached[rel] = response
                tokens += response.get("usage", {}).get("input_tokens", 0)
                db.execute("insert or replace into answers values (?, ?, ?)", (
                    request_key(payloads[rel]), json.dumps(response),
                    datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                ))
        db.commit()

    results = {
        rel: combine(ex, store, rel, payloads[rel], cached[rel]["answers"], facets, mix)
        for rel in targets if rel in cached
    }

    # Writes happen under note-extract's lock so they never interleave with an
    # extraction run; Store.update re-reads each file first, so a hand edit
    # synced in meanwhile is kept.
    written = 0
    with open(args.lock, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        store = ex.Store(args.vault)
        for rel in store.folder("Thoughts"):
            if wanted and rel not in wanted:
                continue
            meta = store.meta(rel)
            new = results.get(rel)
            if new is None and not any(k in meta for k in FIELDS):
                continue
            if new is None and eligible(ex, meta) and rel in payloads:
                continue  # API failed this run; keep the old score
            if all(meta.get(k) == (new or {}).get(k) for k in FIELDS):
                continue
            store.update(rel, lambda m, _b, new=new: apply_fields(m, new))
            written += 1
    db.execute("insert into runs values (?, ?, ?, ?)", (
        datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        len(missing), tokens, written,
    ))
    db.commit()
    print(f"scored {len(results)} thought(s): {len(missing)} API call(s), "
          f"{tokens} input tokens, {written} file(s) updated", flush=True)


def show(args) -> None:
    """Print the current ranking from the vault (no API calls)."""
    ex = load_extract(args.extract_module)
    store = ex.Store(args.vault)
    rows = []
    for rel in store.folder("Thoughts"):
        meta = store.meta(rel)
        if isinstance(meta.get("score"), (int, float)) and eligible(ex, meta):
            rows.append((meta["score"], rel.split("/", 1)[1], meta.get("score-parts", ""),
                         meta.get("score-unsure", False)))
    rows.sort(key=lambda r: -r[0])
    for score, title, parts, unsure in rows[: args.limit]:
        print(f"{score:6.3f}{'?' if unsure else ' '} {title}")
        if args.verbose:
            print(f"         {parts}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True, help="directory for the answer cache")
    parser.add_argument("--lock", type=Path, required=True, help="note-extract's lock file")
    parser.add_argument("--extract-module", type=Path, required=True, help="path to note-extract.py")
    parser.add_argument("--key-file", type=Path, help="file holding the TypeSafe API key")
    parser.add_argument("--model", default="jev-1.13.0",
                        help="pinned so cached answers and tuned weights stay comparable")
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--dry-run", action="store_true", help="print requests, call nothing, write nothing")
    parser.add_argument("--show", action="store_true", help="print the current ranking and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="with --show: include score parts")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("notes", nargs="*", help="thought titles to score (default: all open)")
    args = parser.parse_args()
    if args.show:
        show(args)
        return
    if not args.dry_run and not (args.key_file and args.key_file.exists()):
        sys.exit(f"no TypeSafe API key at {args.key_file}")
    run(args)


if __name__ == "__main__":
    main()
