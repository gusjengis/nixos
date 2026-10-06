# Extraction Plan (implemented, iterating)

Second processing stage after normalization (see `CAPTURE_PLAN.md`). Turns each
`Normalized/<stamp>.md` into atomic thought notes with types, tags, entities and
typed links. Build order steps 1-5 are implemented in
`system/hosts/omega/note-extract.py` (see "Implementation" below); this file
stays the working design.

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
8. Markers carry over: `?` / "look up" -> `question`.
   Crossed-out items are kept as dropped history, not live tasks.
9. Duplicates merge; nothing is deleted. Source links keep every capture.
10. Extraction is not interpretation. No inferred values or goals the note does
    not state. Inferring the hierarchy of values is a later, separate pass,
    probably with a smarter model.

## First results and known issues (2026-10-05)

The vault's first `Thoughts/` and `Entities/` were not produced by the
service: they were copied in from a test run on a copy of the vault (51 notes
-> 333 thoughts, 78 entities, 247 cross-note links, 0 merges, ~30 min), with
the state database copied alongside so the service only extracts what changed
since. That run used a stricter entity rule (proper names only); the prompt now
also allows owned objects and places such as the car, the toilet, the passport
or the garage. The whole real vault was subsequently re-extracted with
`note-extract --force` using prompt `v3`: 51 notes, 334 thoughts matched and
kept, 3 new thoughts, 39 new entities, no merges or failures, 11 min 51 s.
`Toilet`, `Passport`, and `2020 RAV4 Limited` now have entity notes and
`mentions` / `mentioned-by` links. Omega runs this version; Obsidian Sync
completed after the run. Existing user fields and unmatched orphaned notes
were preserved.

Outstanding problems, roughly by importance:

1. **No merges.** Qwen rejected every candidate in the final run, even
   "Apply for jobs" vs "Apply for jobs and collect notes" (0.90) and "Anime is
   too stimulating" vs "Question if anime is too stimulating" (0.90). The
   pipeline works (an earlier prompt merged 5); the `SAME_PROMPT` ("when in
   doubt, different") is just conservative. Loosen it if duplicates pile up.
2. **Link quality is about v1:** roughly 70% look right in samples. Remaining
   errors: direction still sometimes reversed (`motivated-by` vs `motivates`,
   "Usable local LLM answers ..."), `serves` and `example-of` overused (55 and
   32 of 247), occasional contradictory pairs (a thought both `part-of` and
   `has-part` of the same target, from the segmenter plus a later link).
3. **Matching embeddings are compressed:** random pairs score ~0.51, p99 0.72,
   and related-but-different thoughts 0.80-0.90, so similarity alone cannot
   separate duplicates from neighbours; Qwen has to decide every case above
   the 0.75 floor (234 cross-note pairs above it in the test vault).
4. **Search ranking is rough:** "car repairs" did not rank the RAV4 wheel well
   thoughts near the top; FTS uses OR over words and the retrieval half has
   not been tuned. Reranking with Qwen is the planned fix.
5. **Segmentation is not deterministic across runs:** the prompt includes the
   current tags and entities, so re-extracting a note can change types, tags
   and body wording (titles and ids stay). Re-extraction only happens when the
   normalized note changes or with `--force`.
6. **Titles stay terse** for terse bullets ("hyprlog track desktop",
   "Test drives, record"), and many short bullets are flagged `unclear`.
7. **Cost:** a full backfill holds Qwen for ~30 min (one call per 250 words,
   up to 3 dedup checks and 1-2 link calls per thought); the OpenCode
   auto-router queues behind it. Steady state is a few calls per new capture.
8. **Hand-made entities are not used for aliases:** the pipeline never edits
   an existing entity except to add `mentioned-by`, so a new alias found in a
   note is not added to it.
9. **Entity classification still needs tuning:** prompt `v3` explicitly asks
   for unnamed concrete objects as well as named entities, which successfully
   adds Toilet and Passport. Qwen also creates abstract entities (for example
   memories, anime, agent, LLM) despite explicit exclusions. These preliminary
   results are retained for inspection, not automatically deleted.
10. **Re-extraction adds links but does not reconcile old ones:** existing
    `mentions` and relation properties, including entity backlinks, remain
    when a later segmentation stops producing them. Orphaned thoughts retain
    their links. Inspect graph results with this limitation in mind.

Manual forced runs and scheduled runs share a lock. Scheduled extraction now
waits behind a manual run instead of failing with "another note-extract is
running", so captures arriving during a backfill are processed afterwards.

## State before implementation (2026-10-04)

- Models live on omega: `qwen3.8:27b` (48k ctx, GPU), `jina-v5-retrieval`
  (GPU), `jina-v5-matching` (CPU), all resident. ~0.9 GB VRAM headroom.
- `Normalized/` is complete and kept current; this stage reads it.
- Matching scores on known duplicates: 0.51-0.57; unrelated: 0.19-0.33. Merge
  threshold needs tuning with an LLM confirm step, not a raw cutoff.

## Build order

1. ✓ Segment pass alone, dry run printing JSON (`note-extract --dry-run`).
2. ✓ Write `Thoughts/` files with in-note links, plus entities; `note-delete`
   handles thoughts (see `DATA_MODEL.md`, Deletion).
3. ✓ Embeddings, dedup and merge.
4. ✓ Cross-note links.
5. ✓ Bases views (`Thoughts.base`: open tasks by tag, purchases, open
   questions, projects, ideas, recurring, recent).
6. Later: resurfacing (daily digest, "Active Quests" in Quickshell), routing hard
   cases to paid models, agents that open PRs for review, search endpoint and
   launcher entry (the CLI exists).

## Implementation (2026-10-05)

Code: `system/hosts/omega/note-extract.py`, units in `notes.nix`.

- `note-extract.service` (oneshot) is started by `note-extract.path` (any
  change in `Normalized/`) and `note-extract.timer` (15 min after the last
  run). A note is extracted when the hash of its body differs from the one
  recorded at its last extraction, so re-normalizing a note re-extracts it.
- State, disposable: `/var/lib/note-extract/extract.sqlite` holds embeddings
  (one table, keyed by model + dims), the FTS5 index, `extracted` (stem ->
  body hash) and `merges` (the merge log: when, source, merged title, target,
  score). Deleting it re-embeds everything and re-extracts every note; the
  re-extraction matches existing thoughts, so nothing is duplicated.
- Per note: segment (one Qwen call per <= 250-word piece, split at blank-line
  groups, no overlap so no line is segmented twice; a piece whose answer hits
  the output cap is halved and retried) -> match against the
  thoughts this note produced before -> dedup -> create -> in-note links and
  entities -> refresh indexes -> link each new thought across notes.
- The segment prompt receives the existing tags with counts and the known
  entities with aliases, so tags converge and entity names are reused; an
  entity is then resolved by exact name or alias, else created.
- Dedup and cross-note linking skip thoughts from the same capture: the
  segmenter already merged in-note duplicates and set in-note relations from
  the note's structure. Without this, siblings ("Disable Obsidian Sync on
  pc / legion / mac") were merged or cross-linked with `similar-to`.
- Merge: matching similarity >= 0.75 (`--merge-floor`, top 3) and Qwen says
  "same thought". Embedding "title + rewritten text" scores higher than the
  earlier raw-text measurement: random pairs ~0.51 (p99 0.72), merged
  duplicates 0.79-0.92, so the floor sits above the random p99. The survivor gains the `source`, `mentions_count` becomes
  its number of sources, tags are unioned, and the new wording is appended as
  another quote.
- Re-extraction: new thoughts are paired with the note's previous ones by
  equal title or matching similarity >= 0.8, best pairs first. Paired thoughts
  keep title, id, `status` and user fields; types, tags and (for a
  single-source thought) the body are refreshed. Unpaired old thoughts become
  `orphaned: true`, or lose this source if they have others.
- Linking: shortlist of 10 by matching similarity, Qwen may add up to 3
  searches (retrieval model, 5 results each), then one more call picks
  relations. Each relation is given as a sentence "NEW <relation> C" in both
  directions (reverse names are flipped when written), and every link needs a
  one-sentence `why`, which the service log prints. Without these, Qwen
  confused directions and overused `alternative-to` / `similar-to`.
- Every Qwen call has an output cap and length limits in its JSON schema: under
  a grammar the model can loop inside a string until the context is full,
  which once held the GPU for over ten minutes. A capped linking answer means
  no links for that thought; a capped dedup answer means "different".
- `note-search QUERY` (omega): FTS5 + retrieval embeddings over Thoughts,
  Entities and Normalized, merged by reciprocal rank fusion.
- `Thoughts.base` is copied into the vault root once (repo copy beside the
  script) and is then the user's to edit.
- Cost: ~10 s for a short note, ~3.5 min to segment the 830-word brain dump;
  linking is 1-2 calls per new thought. A full backfill of ~50 notes takes on
  the order of an hour and queues other Qwen callers (the auto-router) while
  it runs.

## Decisions taken (2026-10-04)

Recorded in `DATA_MODEL.md`: titles as file names (`id` in frontmatter),
`Thoughts/` + `Entities/`, `types` for kind and free `tags` for subject, projects
as `project` thoughts linked with `part-of` (not tags), automatic merge after
Qwen confirms, captures only (no `TODOS.md` or repo docs yet). Start with that
model as-is and revise from real use.
