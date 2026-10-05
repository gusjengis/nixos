# Extraction Plan (draft, iterating)

Second processing stage after normalization (see `CAPTURE_PLAN.md`). Turns each
`Normalized/<stamp>.md` into atomic thought notes with types, tags, entities and
typed links. Nothing here is implemented yet; this is the working design.

Requirements the author already wrote down in raw notes:

- `2026-09-30-211638`: dedup across notes, tree / hierarchy of values, automatic
  todo and goal/requirement detection, extrapolation of values, interlinking,
  detection of questions and unfinished decisions.
- `2026-09-30-202146`: guess parent-child relationships; split nested notes into
  separate files that preserve the relationship via links.
- `2026-09-30-214137`: extract objects/property (e.g. the car) into their own
  notes, referenced by others.
- `2026-10-01-201310`: identify potential purchases.

## Pipeline shape

`Normalized/` -> extract (omega, path-unit watch, same pattern as normalize) ->
`Thoughts/` + `Entities/`.

1. **Segment** (LLM, per normalized note). Split into atomic thoughts; return
   JSON: text, types, tags, entities, task fields, links within the note.
   Indentation already encodes most parent-child structure. Large brain dumps
   are split at blank-line groups so each call stays small.
2. **Resolve** (embeddings + LLM). Embed each new thought, compare against the
   nearest existing ones; the LLM decides "same thought?" for close matches.
   Duplicates **merge**: the existing thought gains a `source` link and its
   `mentions_count` goes up (repetition is a resurfacing signal).
3. **Link** (embeddings + LLM). Embeddings shortlist the top ~8 similar thoughts
   vault-wide; the LLM picks zero or more relation types per pair. Similarity
   alone never creates a link.
4. **Entities**. People, objects, projects, places, tools resolved to an existing
   `Entities/` note or a new one.

Embeddings: see "Embeddings and semantic search" below.

## Embeddings and semantic search

Two task-specific versions of Jina v5 text-small (677M, Qwen3-0.6B base, 1024
dims, Matryoshka-truncatable) run in omega's Ollama, both Q8, 4k context (one
thought or one query per input; long notes are split before embedding):

| Model | Similarity means | Used for | Runs on |
|---|---|---|---|
| `jina-v5-matching` (text-matching) | says the same thing (symmetric) | dedup, link shortlist (thought vs thought) | CPU: background, once per new thought |
| `jina-v5-retrieval` (retrieval) | document answers / is about the query (asymmetric, `Query:` / `Document:` prefixes) | user search, Qwen's own searches during linking | GPU: interactive, latency matters |

Same mechanics (text in, vector out, nearest neighbours); only the training
objective differs. Each step always uses the same model, so the two indexes never
mix. Vectors are incompatible across models.

Storage: SQLite cache on omega, one table per model, keyed by model + dims;
disposable, rebuilt from the vault when a model changes (matching backfill on CPU
~20 min for the whole vault, retrieval ~1 min on GPU). Brute-force cosine over a
few thousand vectors is well under 100 ms; no vector database needed.

Search = hybrid: SQLite FTS5 keyword search (exact names: "Brannon", "K64",
"RAV4", which embeddings handle poorly) merged with retrieval-embedding results
(reciprocal rank fusion). Optional later: rerank the top ~20 with Qwen.

Surfaces: tailnet-only search endpoint on omega, then a CLI and a
Vicinae/Quickshell launcher entry. (Raw notes `2026-10-01-223338` and
`2026-10-01-091833` already ask for this.)

### Qwen searches during linking

Qwen cannot embed; the pipeline searches for it. Linking per new thought:

1. Fixed shortlist: top ~10 by text-matching similarity, always.
2. Qwen may issue up to ~3 `search(query)` calls of its own (retrieval model),
   for links by purpose or cause that do not share wording ("Order RAV4
   moulding" <-> car budget; "Nobody's coming" <-> "Apply for jobs"). Capped agent
   loop, 2-5 Qwen calls per thought.
3. Qwen picks relation types for the union of candidates.

The same search tool can later be handed to OpenCode / paid-model agents working
from the notes.

## Separation rules

1. One thought = one unit you could act on, answer, believe or link on its own.
   Test: would you ever want to check it off, link to it, or find it without its
   siblings?
2. Top-level bullets are candidate thoughts.
3. Child bullets become separate thoughts only if they pass rule 1, and link to
   the parent (`subtask-of` / `part-of`). Children that are reasons, specifics or
   examples stay in the parent's body. ("Order moulding" -> own task under "Fix
   RAV4 wheel well"; "Email, Text, News..." stays inside "AI managing information
   diet".)
4. Every thought must stand alone: resolve pronouns and references ("the car
   mentioned above" -> "2020 RAV4 Limited", bare "Apply!!!" -> "Apply for jobs").
   The source wording is kept as a quote so the rewrite can be checked.
5. Nothing invented. Every thought cites its source lines. Unclear thoughts stay
   as written with `unclear: true`; no guessing.
6. A heading that groups children ("Raw note processing", "Quickshell") becomes
   a `project` or `topic` thought; children link to it.
7. Assistant instructions and junk are excluded: "Test", "Hi Sol! Treat this as a
   prompt" -> `meta`; OCR leftovers -> `noise` (e.g. `2026-10-01-223441`, the model
   saying the page is blank; the OCR blank-page handling needs a fix).
8. Markers carry over: ☆ -> `priority: high`; `?` / "look up" -> `question`.
   Crossed-out items are kept as dropped history, not live tasks.
9. Duplicates merge; nothing is deleted. Source links keep every capture.
10. Extraction is not interpretation. No inferred values or goals the note does
    not state. Inferring the hierarchy of values is a later, separate pass,
    probably with a smarter model.

## Thought types (any number per thought)

| Type | Meaning | Example |
|---|---|---|
| `task` | Something to do (has a status) | Store duvet in garage |
| `reminder` | Task about timing / not forgetting | Talk to Brian about orthodontics |
| `idea` | Possible thing to build or try | GitHub contribution-based Patreon |
| `project` | Container for many tasks and ideas | hyprlog, note processing |
| `requirement` | Constraint on a project | Normalized notes must link both ways |
| `question` | Open, needs an answer | What is rsync? |
| `decision` | Unmade (open) or made (closed) choice | Typst vs LaTeX resumes |
| `goal` | Desired end state | More meaningful job |
| `value` | Principle or belief about what matters | Nobody's coming; own your future |
| `insight` | Observation or claim about the world | Bodybuilding for the mind |
| `quote` | Aphorism or someone else's idea | Criticism is admiration in disguise |
| `resource` | Something to read, watch, check out | Watch *Zeitgeist*; Kaggle course |
| `purchase` | Something to buy (also a task) | AirTags, soap bottles |
| `person-action` | Contact or follow up (also a task) | Call Margie, message Carden |
| `reflection` | Feelings, relationships, self-observation | Leaving Josh's rehearsal was hurtful |
| `log` | Reports a state or something done | Now capturing thoughts easily |
| `meta` / `noise` | Excluded from views | |

Entity types (separate notes in `Entities/`, linked via `mentions`): `person`,
`object` (owned things), `place`, `tool` (software/hardware), `organization`,
`work` (book, video).

## Relation types (directed; reverse written automatically; any number per pair)

| Relation | Reverse | Meaning |
|---|---|---|
| `part-of` | `has-part` | Belongs to a project or topic |
| `subtask-of` | `has-subtask` | Task broken into smaller tasks |
| `depends-on` | `blocks` | Can't do A before B |
| `serves` | `served-by` | Advances a goal or value (the "why") |
| `motivated-by` | `motivates` | Reason or experience behind it |
| `answers` | `answered-by` | Resolves a question or decision |
| `raises` | `raised-by` | Leads to a question |
| `elaborates` | `elaborated-by` | Refines or adds detail to an earlier thought |
| `supersedes` | `superseded-by` | Newer version replaces older |
| `alternative-to` | (symmetric) | Competing options |
| `contradicts` | (symmetric) | Tension between thoughts |
| `example-of` | `has-example` | Specific case of a general idea |
| `inspired-by` | `inspired` | Came from a source, person or thought |
| `similar-to` | (symmetric) | Related, no stronger link applies (use least) |
| `mentions` | `mentioned-by` | Thought -> entity |
| `source` | `extracted` | Thought -> normalized note |

`serves` / `motivated-by` build the hierarchy of values over time.

## Note format

`Thoughts/Order RAV4 wheel well moulding.md`:

```yaml
id: th-20260930214137-02
types: [task, purchase]
status: todo             # todo | doing | waiting | done | dropped | someday
priority: normal
tags: [area/car, area/home-maintenance]
captured: 2026-09-30T21:41:37-07:00
mentions_count: 1
source: ["[[Normalized/2026-09-30-214137]]"]
mentions: ["[[Entities/2020 RAV4 Limited]]"]
subtask-of: ["[[Thoughts/Fix RAV4 rear-left wheel well]]"]
extractor: qwen3.8:27b / v1
```

Body: standalone wording, then a quote of the source line.

Links live in frontmatter: Obsidian graph/backlinks count property links, Bases
(core plugin, mobile too) can query by type/status/tags (first resurfacing
surface), and ExcaliBrain/Breadcrumbs can draw typed hierarchies. A link with
several types = same target under several relation keys.

## Ownership

- Generated fields (text, types, tags, links) are rebuildable from `Normalized/`.
- User fields (`status`, `priority`, anything added by hand) must survive a
  rebuild: stable thought IDs, rebuilt thoughts matched to old ones, user fields
  carried over. A thought that disappears is marked `orphaned`, not deleted.
- Raw edit -> re-normalize -> re-extract only that note's thoughts.

## Build order

1. Segment pass alone, dry run printing JSON. Tune on the two big brain dumps
   (`2026-10-01-091833` has ~150 items).
2. Write `Thoughts/` files with in-note links, plus entities.
3. Embeddings, dedup and merge.
4. Cross-note links.
5. Bases views (open tasks by area, purchases, open questions). First point
   where it becomes useful.
6. Later: resurfacing (daily digest, "Active Quests" in Quickshell), routing hard
   cases to paid models, agents that open PRs for review.

## Open questions

1. File names: readable titles (generated once, never renamed) or IDs + alias?
   Leaning titles.
2. Folder names: `Thoughts/` + `Entities/`, or `Processed/` as an earlier note said?
3. Tags: free-form, or a fixed area list the model can only propose additions to?
   Leaning fixed list.
4. Import `TODOS.md` and older vault notes once, or captures only?
5. Dedup: merge automatically, or "possible duplicate" links to confirm at first?
6. Types to add, remove or rename?
