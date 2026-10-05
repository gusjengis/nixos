# Extraction Plan (draft, iterating)

Second processing stage after normalization (see `CAPTURE_PLAN.md`). Turns each
`Normalized/<stamp>.md` into atomic thought notes with types, tags, entities and
typed links. Nothing here is implemented yet; this is the working design.

The data model it produces (folders, types, tags, relations, note formats,
ownership) is specified in `DATA_MODEL.md`; this file covers how extraction works.
System overview and where everything runs: `SECOND_BRAIN.md`.

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

Limits: 4k tokens per input (~3,000 words). Batch size (512) is only how many
tokens are processed per step; output is unchanged. Inputs over ~2k tokens are
chunked at headings / blank-line groups with slight overlap; a note's search
score is its best chunk. Atomic thoughts never come close.

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
   a `project` thought (or a plain thought when it is only a subject); children
   link to it with `part-of`.
7. Assistant instructions and junk are excluded: "Test", "Hi Sol! Treat this as a
   prompt" -> `meta`; OCR leftovers -> `noise` (e.g. `2026-10-01-223441`, the model
   saying a page is blank; blank pages are now handled upstream).
8. Markers carry over: ☆ -> `priority: high`; `?` / "look up" -> `question`.
   Crossed-out items are kept as dropped history, not live tasks.
9. Duplicates merge; nothing is deleted. Source links keep every capture.
10. Extraction is not interpretation. No inferred values or goals the note does
    not state. Inferring the hierarchy of values is a later, separate pass,
    probably with a smarter model.

## Current state (2026-10-04)

- Models live on omega: `qwen3.8:27b` (48k ctx, GPU), `jina-v5-retrieval`
  (GPU), `jina-v5-matching` (CPU), all resident. ~0.9 GB VRAM headroom.
- `Normalized/` is complete and kept current; this stage reads it.
- Matching scores on known duplicates: 0.51-0.57; unrelated: 0.19-0.33. Merge
  threshold needs tuning with an LLM confirm step, not a raw cutoff.

## Build order

1. Segment pass alone, dry run printing JSON. Tune on the two big brain dumps
   (`2026-10-01-091833` has ~150 items).
2. Write `Thoughts/` files with in-note links, plus entities; extend
   `note-delete` to thoughts (see `DATA_MODEL.md`, Deletion).
3. Embeddings, dedup and merge.
4. Cross-note links.
5. Bases views (open tasks by area, purchases, open questions). First point
   where it becomes useful.
6. Later: resurfacing (daily digest, "Active Quests" in Quickshell), routing hard
   cases to paid models, agents that open PRs for review.

## Decisions taken (2026-10-04)

Recorded in `DATA_MODEL.md`: titles as file names (`id` in frontmatter),
`Thoughts/` + `Entities/`, `types` for kind and free `tags` for subject, projects
as `project` thoughts linked with `part-of` (not tags), automatic merge after
Qwen confirms, captures only (no `TODOS.md` or repo docs yet). Start with that
model as-is and revise from real use.
