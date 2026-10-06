"""Rank open thoughts and sort all thoughts into contexts, using Jev.

Jev is TypeSafe's System One model: given a `state` and typed questions it
returns calibrated scores and yes/no probabilities, never text. One request
per thought carries every question; answers are cached per (state, question),
so editing one facet aim or one context description only re-asks that one
question, and changing a weight costs nothing.

Scoring (open, actionable thoughts): a Score question per facet in the vault's
Facets.md ("how much does this advance <aim>?") plus urgency, effort, unblocks
and a comparison with linked neighbors; code combines them with the weights in
Facets.md into `score`.

Contexts (every visible thought): one yes/no question per note in Contexts/
("is this thought about <description>?"). A thought joins the contexts it
clearly belongs to, most specific first; a context's view also shows its
descendants' thoughts. Each context note gets a nightly-style summary in its
frontmatter (context-score, open, total, top) and a generated block of
embedded Bases views; Dashboard.md lists them all.

The state sent to Jev is small on purpose (Jev loses accuracy on irrelevant
context): the thought, the titles and first lines of the thoughts it links to,
and the names of entities it mentions. Dates, counts and link popularity are
computed in code, never asked.

Fields written (pipeline-owned; see notes/DATA_MODEL.md):
  thoughts: score, score-facet, score-parts, score-unsure, contexts
  contexts: context-score, open, total, top
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

import yaml

API = "https://api.typesafe.ai/v1/systemone"
SCORE_FIELDS = ("score", "score-facet", "score-parts", "score-unsure")
THOUGHT_FIELDS = SCORE_FIELDS + ("contexts",)
CONTEXT_FIELDS = ("context-score", "open", "total", "top")
CONTEXTS = "Contexts"

# Thoughts that can be acted on or resolved; insights, logs, reflections,
# values and quotes are context, not work.
SCORED_TYPES = {
    "task", "reminder", "purchase", "person-action", "idea", "project",
    "question", "decision", "goal", "resource",
}
CLOSED = {"done", "dropped"}

DEFAULT_MIX = {
    "impact": 0.55, "urgency": 0.25, "quick": 0.10, "unblocks": 0.10,
    "local": 0.10, "secondary": 0.2, "blocks-boost": 0.03,
}
UNSURE_BELOW = 0.35
MAX_NEIGHBORS = 12
ASSIGN_AT = 0.6      # noul at or above which a thought joins a context
MAX_CONTEXTS = 3     # per thought, most probable first
RECENT_DAYS = 7      # context-score bonus for recent activity
RECENT_BONUS = 0.05

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
CONTEXT_CRITERIA = {
    "true": "`thought` is mainly about `context`, or is a direct part of it",
    "false": "`thought` only mentions `context` in passing, or is about something else",
}

GEN_BEGIN = "<!-- note-score: generated views below; edit above this line -->"
GEN_END = "<!-- note-score: end of generated views -->"
OPEN_FILTERS = ['status != "done"', 'status != "dropped"', 'status != "someday"']


def load_extract(path: Path):
    """note-extract.py, for its frontmatter helpers: same YAML layout, same
    atomic writes, same Store, so a written file round-trips byte-identically."""
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


# --- contexts ---------------------------------------------------------------

class Contexts:
    """Contexts/*.md: name = file name, `description` = what belongs,
    optional `parent` link to another context."""

    def __init__(self, ex, vault: Path):
        self.ex, self.vault = ex, vault
        self.notes: dict[str, tuple[dict, str]] = {}
        for path in sorted((vault / CONTEXTS).glob("*.md")):
            try:
                meta, body = ex.split_note(path.read_text(encoding="utf-8"))
            except (ValueError, yaml.YAMLError) as exc:
                print(f"{CONTEXTS}/{path.stem}: unreadable frontmatter, skipped: {exc}", flush=True)
                continue
            if str(meta.get("description") or "").strip():
                self.notes[path.stem] = (meta, body)
        self.parent = {}
        for name, (meta, _) in self.notes.items():
            target = ex.target(meta.get("parent") or "")
            parent = target.removeprefix(f"{CONTEXTS}/") if target else None
            self.parent[name] = parent if parent in self.notes and parent != name else None
        for name in self.notes:  # break cycles
            seen, node = {name}, self.parent[name]
            while node:
                if node in seen:
                    self.parent[name] = None
                    break
                seen.add(node)
                node = self.parent[node]

    def ancestors(self, name: str) -> list[str]:
        out, node = [], self.parent.get(name)
        while node:
            out.append(node)
            node = self.parent.get(node)
        return out

    def children(self, name: str) -> list[str]:
        return sorted(n for n, p in self.parent.items() if p == name)

    def subtree(self, name: str) -> list[str]:
        out = [name]
        for child in self.children(name):
            out += self.subtree(child)
        return out

    def path(self, name: str) -> str:
        return " > ".join(reversed([name] + self.ancestors(name)))

    def question(self, name: str) -> dict:
        description = str(self.notes[name][0]["description"]).strip()
        return {
            "type": "noul",
            "instructions": {
                "context": f"{self.path(name)}: {description}",
                "question": "Is `thought` about `context`?",
            },
            "criteria": CONTEXT_CRITERIA,
        }


def context_qid(name: str) -> str:
    return "ctx_" + hashlib.sha1(name.encode()).hexdigest()[:12]


# --- requests ---------------------------------------------------------------

def first_line(ex, body: str, limit: int = 200) -> str:
    return ex.thought_text(body).replace("\n", " ")[:limit]


def eligible(ex, meta: dict) -> bool:
    return (
        ex.visible(meta)
        and str(meta.get("status") or "").lower() not in CLOSED
        and bool(set(map(str, ex.as_list(meta.get("types")))) & SCORED_TYPES)
    )


def build_state(ex, store, rel: str) -> dict:
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
    return {
        "thought": {
            "title": rel.split("/", 1)[1],
            "types": list(map(str, ex.as_list(meta.get("types")))),
            "text": ex.thought_text(body),
            "mentions": [t.split("/", 1)[1] for t in ex.targets(meta, "mentions")],
        },
        "neighbors": neighbors[:MAX_NEIGHBORS],
    }


def score_questions(facets: list[dict], state: dict) -> dict:
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
    if state["neighbors"]:
        questions["local"] = LOCAL_QUESTION
    return questions


def question_key(model: str, state: dict, question: dict) -> str:
    return hashlib.sha256(json.dumps([model, state, question], sort_keys=True).encode()).hexdigest()


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


class Asker:
    """Answers questions from the per-question cache, sending only the
    missing ones (one request per thought)."""

    def __init__(self, db: sqlite3.Connection, model: str, key_file: Path | None, jobs: int):
        self.db, self.model, self.key_file, self.jobs = db, model, key_file, jobs
        self.calls = self.tokens = 0

    def ask(self, requests: dict[str, tuple[dict, dict]]) -> tuple[dict, set]:
        """requests: rel -> (state, {qid: question}).
        Returns (rel -> {qid: answer}, rels that failed)."""
        answers: dict[str, dict] = {}
        missing: dict[str, dict] = {}
        keys: dict[str, dict] = {}
        for rel, (state, questions) in requests.items():
            answers[rel], keys[rel] = {}, {}
            for qid, question in questions.items():
                k = question_key(self.model, state, question)
                keys[rel][qid] = k
                row = self.db.execute("select answer from qa where key = ?", (k,)).fetchone()
                if row:
                    answers[rel][qid] = json.loads(row[0])
                else:
                    missing.setdefault(rel, {})[qid] = question
        failed: set[str] = set()
        if not missing:
            return answers, failed
        api_key = self.key_file.read_text(encoding="utf-8").strip()
        n_questions = sum(len(q) for q in missing.values())
        print(f"asking Jev {n_questions} question(s) about {len(missing)} thought(s)", flush=True)
        now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        with concurrent.futures.ThreadPoolExecutor(self.jobs) as pool:
            futures = {
                pool.submit(call_jev, {"model": self.model, "state": requests[rel][0], "questions": qs}, api_key): rel
                for rel, qs in missing.items()
            }
            for future in concurrent.futures.as_completed(futures):
                rel = futures[future]
                try:
                    response = future.result()
                except Exception as exc:  # one failure must not block the rest
                    print(f"  {rel}: {exc}", flush=True)
                    failed.add(rel)
                    continue
                self.calls += 1
                self.tokens += response.get("usage", {}).get("input_tokens", 0)
                for qid, answer in response["answers"].items():
                    answers[rel][qid] = answer
                    self.db.execute("insert or replace into qa values (?, ?, ?)",
                                    (keys[rel][qid], json.dumps(answer), now))
        self.db.commit()
        return answers, failed


# --- combine ----------------------------------------------------------------

def normalized(questions: dict, answers: dict, qid: str) -> tuple[float, float]:
    top = len(questions[qid]["criteria"]) - 1
    answer = answers[qid]
    return answer["score"] / top, answer.get("confidence", 1.0)


def combine(ex, store, rel: str, questions: dict, answers: dict, facets: list[dict], mix: dict) -> dict:
    meta = store.notes[rel][0]
    contributions = []
    for facet in facets:
        value, confidence = normalized(questions, answers, f"facet_{facet['id']}")
        contributions.append((facet["weight"] * value, value, confidence, facet))
    contributions.sort(key=lambda c: -c[0])
    best = contributions[0]
    rest = sum(c[0] for c in contributions[1:])
    impact = min(1.0, best[0] + mix["secondary"] * rest)

    urgency, urgency_conf = normalized(questions, answers, "urgency")
    effort, _ = normalized(questions, answers, "effort")
    unblocks, _ = normalized(questions, answers, "unblocks")
    local = normalized(questions, answers, "local")[0] if "local" in questions else 0.5
    quick = 1.0 - effort

    score = (
        mix["impact"] * impact + mix["urgency"] * urgency + mix["quick"] * quick
        + mix["unblocks"] * unblocks + mix["local"] * local
    )
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
        + (f" · local {local:.2f}" if "local" in questions else "")
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


def assign(ctx: Contexts, answers: dict) -> list[str]:
    """Most specific contexts the thought clearly belongs to."""
    probable = sorted(
        ((answers[context_qid(n)]["noul"], n) for n in ctx.notes if context_qid(n) in answers),
        reverse=True,
    )
    chosen = [n for p, n in probable if p >= ASSIGN_AT]
    implied = {a for n in chosen for a in ctx.ancestors(n)}
    return [n for n in chosen if n not in implied][:MAX_CONTEXTS]


# --- context notes and dashboard -------------------------------------------

def dump_yaml(data) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=10**6)


def context_views(ctx: Contexts, name: str) -> str:
    links = ", ".join(f'link("{CONTEXTS}/{n}")' for n in ctx.subtree(name))
    base = {
        "filters": {"and": [
            f"contexts.containsAny({links})",
            '!types.contains("meta")', '!types.contains("noise")', "orphaned != true",
        ]},
        "views": [
            {"type": "table", "name": "Next up",
             "filters": {"and": ['file.hasProperty("score")'] + OPEN_FILTERS},
             "order": ["file.name", "score", "status", "contexts", "score-parts"],
             "sort": [{"property": "score", "direction": "DESC"}]},
            {"type": "table", "name": "Questions & decisions",
             "filters": {"and": [
                 {"or": ['types.contains("question")', 'types.contains("decision")']}] + OPEN_FILTERS},
             "order": ["file.name", "types", "score", "captured"],
             "sort": [{"property": "score", "direction": "DESC"}]},
            {"type": "table", "name": "Ideas",
             "filters": {"and": ['types.contains("idea")'] + OPEN_FILTERS},
             "order": ["file.name", "score", "captured"],
             "sort": [{"property": "score", "direction": "DESC"}]},
            {"type": "table", "name": "Insights & reflections",
             "filters": {"or": [f'types.contains("{t}")' for t in
                                ("insight", "reflection", "value", "quote", "log")]},
             "order": ["file.name", "types", "captured"],
             "sort": [{"property": "captured", "direction": "DESC"}]},
            {"type": "table", "name": "Everything",
             "order": ["file.name", "types", "status", "score", "contexts", "captured"],
             "sort": [{"property": "captured", "direction": "DESC"}]},
        ],
    }
    lines = [GEN_BEGIN, ""]
    parent = ctx.parent[name]
    if parent:
        lines.append(f"Part of [[{CONTEXTS}/{parent}|{parent}]]")
    children = ctx.children(name)
    if children:
        lines.append("Sub-contexts: " + " · ".join(f"[[{CONTEXTS}/{c}|{c}]]" for c in children))
    if parent or children:
        lines.append("")
    lines += ["```base", dump_yaml(base).rstrip(), "```", "", GEN_END]
    return "\n".join(lines)


def with_views(body: str, views: str) -> str:
    start, end = body.find(GEN_BEGIN), body.find(GEN_END)
    if start != -1 and end != -1:
        return body[:start] + views + body[end + len(GEN_END):]
    return body.rstrip("\n") + ("\n\n" if body.strip() else "") + views + "\n"


def context_summaries(ex, ctx: Contexts, store, contexts_of: dict) -> dict[str, dict]:
    members: dict[str, list[str]] = {n: [] for n in ctx.notes}
    for rel, names in contexts_of.items():
        for name in names:
            for owner in [name] + ctx.ancestors(name):
                if rel not in members[owner]:
                    members[owner].append(rel)
    cutoff = (datetime.date.today() - datetime.timedelta(days=RECENT_DAYS)).isoformat()
    out = {}
    for name, rels in members.items():
        scored = sorted(
            ((store.meta(r)["score"], r) for r in rels
             if isinstance(store.meta(r).get("score"), (int, float)) and eligible(ex, store.meta(r))),
            reverse=True,
        )
        top5 = [s for s, _ in scored[:5]]
        value = sum(top5) / max(len(top5), 3) if top5 else 0.0
        if any(str(store.meta(r).get("captured") or "")[:10] >= cutoff for r in rels):
            value += RECENT_BONUS
        out[name] = {
            "context-score": round(value, 3),
            "open": len(scored),
            "total": len(rels),
            "top": [ex.link(r) for _, r in scored[:3]],
        }
    return out


DASHBOARD = """\
# Dashboard

Every context, ranked by importance: the mean of its five best open thought
scores (descendants included), plus a bump for activity in the last week.
Recomputed by `note-score` whenever scores or contexts change. Contexts live
in `Contexts/`; rename, merge, re-parent or delete them freely, or edit a
`description` to change what belongs.

```base
filters:
  and:
    - file.inFolder("Contexts")
views:
  - type: table
    name: All contexts
    order: [file.name, context-score, open, total, parent, top]
    sort:
      - property: context-score
        direction: DESC
  - type: table
    name: Top level
    filters:
      and:
        - '!file.hasProperty("parent")'
    order: [file.name, context-score, open, total, top]
    sort:
      - property: context-score
        direction: DESC
  - type: table
    name: New this week
    filters:
      and:
        - 'origin == "discovered"'
        - 'date(created) >= today() - "7d"'
    order: [file.name, description, parent, open, total]
    sort:
      - property: created
        direction: DESC
```

## Top right now

```base
filters:
  and:
    - file.inFolder("Thoughts")
    - file.hasProperty("score")
    - 'status != "done"'
    - 'status != "dropped"'
    - 'status != "someday"'
views:
  - type: table
    name: Top 20
    limit: 20
    order: [file.name, score, contexts, score-facet, status]
    sort:
      - property: score
        direction: DESC
```
"""


# --- run --------------------------------------------------------------------

def open_cache(state: Path) -> sqlite3.Connection:
    state.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(state / "score.sqlite")
    db.execute("drop table if exists answers")  # v1 whole-request cache
    db.execute("create table if not exists qa (key text primary key, answer text, at text)")
    db.execute("create table if not exists runs (at text, calls int, tokens int, written int)")
    return db


def apply_fields(meta: dict, fields: dict | None, keys) -> None:
    for key in keys:
        meta.pop(key, None)
    if fields:
        meta.update(fields)


def run(args) -> None:
    ex = load_extract(args.extract_module)
    facets, mix = parse_facets(args.vault / "Facets.md")
    store = ex.Store(args.vault, dry_run=True)
    ctx = Contexts(ex, args.vault)
    wanted = {f"Thoughts/{n.removeprefix('Thoughts/').removesuffix('.md')}" for n in args.notes}
    thoughts = [
        rel for rel in sorted(store.folder("Thoughts"))
        if ex.visible(store.meta(rel)) and (not wanted or rel in wanted)
    ]

    requests, score_qs = {}, {}
    for rel in thoughts:
        state = build_state(ex, store, rel)
        questions = {context_qid(n): ctx.question(n) for n in ctx.notes}
        if eligible(ex, store.meta(rel)):
            score_qs[rel] = score_questions(facets, state)
            questions.update(score_qs[rel])
        requests[rel] = (state, questions)

    if args.dry_run:
        for rel in thoughts[: args.limit]:
            state, questions = requests[rel]
            print(json.dumps({"model": args.model, "state": state, "questions": questions},
                             indent=2, ensure_ascii=False))
        print(f"{len(thoughts)} thought(s), {len(score_qs)} scored; {len(facets)} facets; "
              f"{len(ctx.notes)} contexts; mix {mix}", file=sys.stderr)
        return

    db = open_cache(args.state)
    asker = Asker(db, args.model, args.key_file, args.jobs)
    answers, failed = asker.ask(requests)

    results = {}
    for rel in thoughts:
        if rel in failed:
            continue
        fields = {}
        if rel in score_qs:
            fields.update(combine(ex, store, rel, score_qs[rel], answers[rel], facets, mix))
        names = assign(ctx, answers[rel])
        if names:
            fields["contexts"] = [ex.link(f"{CONTEXTS}/{n}") for n in names]
        results[rel] = fields

    # Writes happen under note-extract's lock so they never interleave with an
    # extraction run; Store.update re-reads each file first, so a hand edit
    # synced in meanwhile is kept.
    written = 0
    with open(args.lock, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        store = ex.Store(args.vault)
        for rel in store.folder("Thoughts"):
            if (wanted and rel not in wanted) or rel in failed:
                continue
            meta = store.meta(rel)
            new = results.get(rel)
            if new is None and not any(k in meta for k in THOUGHT_FIELDS):
                continue
            if all(meta.get(k) == (new or {}).get(k) for k in THOUGHT_FIELDS):
                continue
            store.update(rel, lambda m, _b, new=new: apply_fields(m, new, THOUGHT_FIELDS))
            written += 1

        if not wanted:
            contexts_of = {
                rel: [ex.target(v).removeprefix(f"{CONTEXTS}/") for v in ex.as_list(store.meta(rel).get("contexts"))]
                for rel in store.folder("Thoughts") if ex.visible(store.meta(rel))
            }
            contexts_of = {r: [n for n in ns if n in ctx.notes] for r, ns in contexts_of.items()}
            summaries = context_summaries(ex, ctx, store, contexts_of)
            for name in ctx.notes:
                path = args.vault / CONTEXTS / f"{name}.md"
                if not path.exists():
                    continue
                text = path.read_text(encoding="utf-8")
                meta, body = ex.split_note(text)
                apply_fields(meta, summaries[name], CONTEXT_FIELDS)
                new_text = ex.join_note(meta, with_views(body, context_views(ctx, name)))
                if new_text != text:
                    ex.write_atomic(args.vault, path, new_text)
                    written += 1
            dashboard = args.vault / "Dashboard.md"
            if not dashboard.exists():
                ex.write_atomic(args.vault, dashboard, DASHBOARD)

    db.execute("insert into runs values (?, ?, ?, ?)", (
        datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        asker.calls, asker.tokens, written,
    ))
    db.commit()
    unplaced = sum(1 for r in results if "contexts" not in results[r])
    print(f"{len(results)} thought(s): {len(score_qs)} scored, {unplaced} in no context; "
          f"{asker.calls} API call(s), {asker.tokens} input tokens, {written} file(s) updated", flush=True)


def show(args) -> None:
    """Print the current ranking from the vault (no API calls)."""
    ex = load_extract(args.extract_module)
    store = ex.Store(args.vault)
    rows = []
    for rel in store.folder("Thoughts"):
        meta = store.meta(rel)
        if isinstance(meta.get("score"), (int, float)) and eligible(ex, meta):
            names = ", ".join(ex.target(v).split("/", 1)[-1] for v in ex.as_list(meta.get("contexts")))
            rows.append((meta["score"], rel.split("/", 1)[1], meta.get("score-parts", ""),
                         meta.get("score-unsure", False), names))
    rows.sort(key=lambda r: -r[0])
    for score, title, parts, unsure, names in rows[: args.limit]:
        print(f"{score:6.3f}{'?' if unsure else ' '} {title}" + (f"  [{names}]" if names else ""))
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
    parser.add_argument("notes", nargs="*", help="thought titles to process (default: all)")
    args = parser.parse_args()
    if args.show:
        show(args)
        return
    if not args.dry_run and not (args.key_file and args.key_file.exists()):
        sys.exit(f"no TypeSafe API key at {args.key_file}")
    run(args)


if __name__ == "__main__":
    main()
