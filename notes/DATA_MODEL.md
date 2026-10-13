# Second Brain Data Model (v1.5)

The shape of everything the pipeline writes into the Obsidian vault. This is a
first pass meant to be used, judged in practice, and revised. Record changes
here (bump the version and note what changed at the bottom) so the extractor
prompt and this file never disagree.

Overview of the whole system: `SECOND_BRAIN.md`. How extraction produces this:
`EXTRACTION_PLAN.md`.

## Folders

| Folder | Holds | Written by | Hand edits |
|---|---|---|---|
| `Raw/` | Captures, one per capture event, plus `Raw/Images/` page images | capture channels | yes; the record of truth |
| `Normalized/` | One cleaned note per raw note, same file name | normalizer (omega) | no; regenerated |
| `Thoughts/` | One atomic thought per file | extractor (omega) | user fields only (below) |
| `Entities/` | People, objects, places, tools, organizations, works | extractor (omega) | yes, freely |
| `Contexts/` | One note per context (area of focus), nested by `parent` | seeded, then scorer discovery | yes; description, parent, name, deletion |
| `Projects/` | Durable project hubs spanning repositories | user/explicit pilot seed | yes |
| `Repositories/` | Logical Git repositories, not individual checkouts | session processor | yes; outside generated sections |
| `Sessions/OpenCode/` | One linked note per conversation | session processor | yes; outside generated sections |
| `Sessions/OpenCode/Transcripts/<device>/` | Sanitized conversation records, updated per session | local collectors | no; regenerated from local OpenCode databases |
| `Sessions/OpenCode/Reviews/` | Evidence-backed closure and new-thought proposals | session processor | yes; outside generated sections |

Capture-derived normalized notes and thoughts can be rebuilt from `Raw/`, but
user-owned lifecycle decisions must be retained. Session notes/reviews rebuild
from pooled transcripts; transcripts require the originating databases to
regenerate. Project hubs are user-owned. Nothing is deleted
automatically; `note-delete` is the only deletion path.

## Design decisions (v1)

1. **File names are titles.** `Thoughts/Order RAV4 wheel well moulding.md`, so
   the graph view and links read naturally. Titles are generated once and never
   renamed by the pipeline (renaming breaks links and hand edits). The stable
   identity is `id` in frontmatter. Title rules: short (≤ ~60 chars), imperative
   for actions ("Call Margie"), a phrase or claim otherwise; characters Obsidian
   or file systems reject (`/ \ : * ? " < > | # ^ [ ]`) are dropped; a collision
   gets ` (2)`, ` (3)`.
2. **Types and tags are different things.**
   - `types` says *what kind of thought* it is (task, idea, question...). Fixed
     vocabulary below. Drives views and status handling.
   - `tags` say *what it is about* (subject matter). Free-form, chosen by the
     model: lowercase, kebab-case, singular, 1-4 per thought (`car`,
     `note-processing`, `job-search`, `home-automation`). The extractor is given
     the existing tags with counts and must reuse one when it fits, so the set
     converges instead of sprawling. Prune or merge tags by hand later if needed.
3. **Projects are notes, not tags.** Captured project thoughts retain type
   `project` in `Thoughts/`. Durable project hubs may live in `Projects/`, and
   thoughts link to them with `part-of`. A repository can implement multiple
   projects, and a project can span repositories. Session `ran-in` records the
   working repository; `concerns` records actual subject, never inferred solely
   from working directory.
4. **Entities are separate notes** in `Entities/`, linked with `mentions`. Things
   that exist (the RAV4, Brian, Tailscale) rather than thoughts about them.
5. **Links live in frontmatter, one property per relation type.** Obsidian's
   graph and backlinks count property links; Bases can filter on them. A pair
   with several relations appears under several properties.
6. **Duplicates merge automatically**, but only when the matching-embedding
   shortlist finds a close candidate *and* Qwen confirms "same thought". The
   surviving thought gains a `source` and its `mentions_count` goes up. Merges
   are logged on omega so a bad one can be found and undone. Everything is
   rebuildable, so being wrong is cheap.
7. **Scope: captures plus a session-evidence pilot.** `TODOS.md`, older vault
   notes and Markdown from other repos are not imported yet. OpenCode transcripts
   have their own pipeline: session summaries and proposed reconciliation, not
   indiscriminate thought extraction.

## Thought types (`types`, any number per thought)

| Type | Meaning | Example |
|---|---|---|
| `task` | Something to do (has `status`) | Store duvet in garage |
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
| `purchase` | Something to buy (implies `task`) | AirTags, soap bottles |
| `person-action` | Contact or follow up (implies `task`) | Call Margie, message Carden |
| `reflection` | Feelings, relationships, self-observation | Leaving Josh's rehearsal was hurtful |
| `log` | Reports a state or something done | Now capturing thoughts easily |
| `meta` | Instructions to an assistant, tests | "Hi Sol! Treat this as a prompt" |
| `noise` | OCR or dictation junk | |

`meta` and `noise` are kept (nothing is lost) but excluded from views.

## Entity types (`Entities/`, `type`)

`person`, `object` (owned things), `place`, `tool` (software or hardware),
`organization`, `work` (book, video, course).

An entity is a concrete thing, named or not: Brian, the 2020 RAV4 Limited, the
toilet, the passport, the garage, Tailscale. Abstract concepts, activities and
categories ("local LLM", "diet", "job search") are not entities; they are
tags or thoughts. Once a specific entity exists the extractor uses it, so
"my car" resolves to the RAV4 rather than to a separate "car".

## Relation types (directed; reverse written on the target automatically)

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
| `source` | (`extracted` not written) | Thought -> normalized note(s) |

`serves` / `motivated-by` are what will grow the hierarchy of values.

## Thought note format

`Thoughts/Order RAV4 wheel well moulding.md`:

```yaml
---
id: th-20260930214137-02
types: [task, purchase]
status: todo
tags: [car]
captured: 2026-09-30T21:41:37-07:00
mentions_count: 1
source: ["[[Normalized/2026-09-30-214137]]"]
mentions: ["[[Entities/2020 RAV4 Limited]]"]
subtask-of: ["[[Thoughts/Fix RAV4 rear-left wheel well]]"]
extractor: qwen3.8:27b / v1
---
Order replacement moulding for the rear-left wheel well of the 2020 RAV4 Limited.

> - Need to order moulding
```

Body: the thought rewritten to stand alone, then the source wording as a quote
so the rewrite can be checked. Each capture merged into it later appends its
own wording as another quote.

Frontmatter is written with block lists (`- item` under the key), as Obsidian
writes it, pipeline fields first in the order above, user fields after.

| Field | Values | Owner |
|---|---|---|
| `id` | `th-<capture stamp>-<nn>`, never changes | pipeline |
| `types` | list from the table above | pipeline |
| `status` | `todo` `doing` `waiting` `done` `dropped` `someday` `dealt-with`; any thought may be marked `dealt-with` | **user** after creation |
| `status-source`, `status-at` | manual lifecycle provenance and UTC timestamp, when changed with CLI | **user** |
| `status-reason`, `resolution`, `evidence` | optional closure reason, outcome, and evidence links | **user** |
| `tags` | free subject tags | pipeline |
| `captured` | earliest capture time | pipeline |
| `mentions_count` | number of captures merged into this thought (= number of `source` entries) | pipeline |
| `source` | normalized notes it came from | pipeline |
| relation properties | lists of links | pipeline |
| `unclear` | `true` when the extractor could not resolve meaning | pipeline |
| `orphaned` | `true` when a rebuild no longer produces it | pipeline |
| `extractor` | model / prompt version | pipeline |
| `score` | float rank key, higher = more important (open, actionable thoughts only) | scorer |
| `score-facet` | facet from `Facets.md` contributing most | scorer |
| `score-parts` | readable breakdown: impact (per facet), urgency, quick, unblocks, local | scorer |
| `score-unsure` | `true` when Jev was split on the facet or urgency rating | scorer |
| `contexts` | links to the most specific `Contexts/` notes it belongs to (≤ 3) | scorer |
| anything else | | **user** |

The scorer (`note-score`, omega) asks Jev one request per open thought (the
thought, its linked neighbors' titles and first lines, mentioned entity names)
with a Score question per facet in the vault's `Facets.md` plus urgency,
effort, unblocks and a neighbor comparison, and combines them with the weights
in `Facets.md`. To the extractor these are ordinary user fields, so they
survive re-extraction. The scorer rewrites them whenever its inputs change and
removes them when a thought is closed; hand edits to them are overwritten.

User-owned fields survive re-extraction: rebuilt thoughts are matched to the
old ones by `id` (or by content when ids shift) and user fields are carried
over. A thought a rebuild no longer produces is marked `orphaned: true`, not
deleted.

## Thought lifecycle and session evidence (v1.5)

`dealt-with` means this thought no longer needs attention, regardless of type.
It does not mean the original thought was false or worthless. Open views exclude
it; historical views retain it. Existing `done`, `dropped`, and `someday`
conventions remain supported. Edit the visible `status` property directly, or use:

```bash
thought-status "Start extraction process" --resolution completed --reason "Verified in session" --evidence "[[Sessions/OpenCode/session-note]]"
thought-status "Start extraction process" --reopen
```

The CLI preserves body bytes and dates, writes atomically, and refuses an edit
that changed during the update. On omega pass `--lock /var/lib/note-extract/lock`;
else its default vault-local lock coordinates local CLI writers only. Neither
lock coordinates Obsidian edits or remote sync. `note-score --refresh-views`
refreshes generated views/counts and removes closed scores offline without
classification or API calls. Existing dashboard/Base customizations are retained.

Each machine's collector reads OpenCode SQLite in a read-only snapshot and
publishes ordinary Markdown through Obsidian Sync. The editable capture policy
is `home/features/agents/opencode/session-capture.json`. `include_sessions` is
an explicit pilot allowlist; remove it or set `[]` for all top-level sessions.
`--session` overrides that list for a manual run. `exclude_directories` and
`include_children` control scope; `session_projects` supplies explicit project
links. Repository mappings reconcile known roots across machines; otherwise
normalized Git remote identifies the repo, falling back to OpenCode's Git root
commit or a device-scoped local workspace identity.

Transcripts include user/assistant text and sanitized tool inputs/results.
Internal reasoning, system messages, attachments, synthetic file text, arbitrary
metadata and known credential-path tool results are excluded. Secret-pattern
redaction is best-effort, not a guarantee; review privacy before broad rollout.
Literal transcript content is code-indented to avoid incidental graph links.
Session identity is device-independent; each device retains its own transcript
copy, and the graph note links all copies, using the freshest for review. Copies
with divergent histories are retained, not semantically merged.

Central `opencode-session-process` runs on omega, renders readable session and
repository notes, and uses the resident model for evidence summaries and
reconciliation proposals. Supplied transcript blocks and candidate thoughts are
bounded; relevant earlier blocks and latest reports are preferred, and omitted
coverage is explicit. Model paths and evidence IDs are validated against supplied
inputs; output text cannot inject graph links. Source revisions and input hashes
invalidate reviews; stale output is marked pending. Human annotations outside
generated sections survive. Cache/state is disposable.

**Pilot safety boundary:** no automatic thought closure or new-thought extraction.
Reviews cite exact pooled transcript blocks, distinguish user-reported,
assistant-claimed and tool-observed information, and leave acceptance to the user.
No nightly repository exploration is implemented yet.

## Context note format

`Contexts/Sleep.md`:

```yaml
---
type: context
description: 'Sleep: bedtime, wake-up time, getting enough sleep, ...'
parent: '[[Contexts/Health]]'   # optional; nesting
origin: seeded                   # seeded | discovered | user
created: 2026-10-05
context-score: 0.71              # scorer: mean of top-5 open scores (subtree) + recency bump
open: 12                         # scorer
total: 30                        # scorer
top: ['[[Thoughts/...]]', ...]   # scorer: three best open thoughts
---
(free text)
<!-- note-score: generated views ... -->  embedded Bases views, rewritten by the scorer
```

Jev is asked, per thought, "is this about <description>?" for every
context; a thought joins contexts at noul ≥ 0.6, keeping only the most
specific (an ancestor is implied). A context's views include its whole
subtree. `Dashboard.md` (created once, then the user's) ranks contexts by
`context-score`. Renaming a context note breaks its links until the next run
reassigns thoughts.

Context classification uses the thought alone; priority scoring also uses
one-hop neighbors. Answers are cached per `(model, state, question)`: editing
one description or facet aim re-asks only that question, not every question.

Nightly discovery uses the extractor's matching embeddings for unassigned
thoughts. At least five thoughts must have cosine similarity >= 0.75 to the
same seed. Qwen decides whether the group is coherent and proposes a name,
description and existing parent. New contexts use `origin: discovered` and
appear in Dashboard's New this week view. Rejected/processed groups are
fingerprinted to avoid naming the same group every night. No sufficiently
tight group means no new context, not a miscellaneous catch-all.

Context score is a task-score rollup, not an independent model judgment of
the project: the five highest actionable scores divided by at least three,
plus 0.05 when any member was captured within seven days. Counts include
descendants; the same thought can contribute to several contexts. This is a
starting heuristic, not a validated measure of life importance.

## Entity note format

`Entities/2020 RAV4 Limited.md`:

```yaml
---
id: en-2020-rav4-limited
type: object
aliases: [RAV4, the car]
tags: [car]
---
```

Body is free for hand-written notes. `mentioned-by` (written by the pipeline,
like every reverse relation) and Obsidian's backlinks list every thought about
it. Once created, the pipeline only ever adds `mentioned-by` entries; names,
aliases and type are the user's.

## Views

`Thoughts.base` in the vault root (Obsidian Bases): open tasks grouped by tag,
purchases, open questions, projects, ideas, recurring (`mentions_count` > 1),
recent. `meta`, `noise` and orphaned thoughts are filtered out. Created once by
the extractor from `system/hosts/omega/Thoughts.base`; edits in the vault are
kept.

## Deletion

`note-delete <stem>` / `--latest` removes a raw note, its page images and its
normalized note; with extraction it must also handle `Thoughts/`: a thought
whose only `source` is that note is deleted, one with several sources loses
that source. Found by scanning `source`, so no separate registry is needed.
Links to deleted thoughts are removed from the remaining thoughts and
entities. `note-delete --orphans` also covers thoughts whose sources are all
gone.

## Changelog

- v1 (2026-10-04): initial model.
- v1.1 (2026-10-05): implemented (`note-extract`, prompt `v1`). Clarified:
  `mentions_count` = number of sources; merges append a quote; frontmatter
  layout; entities get `mentioned-by`; `Thoughts.base` views; note-delete
  drops dangling links. Entities include unnamed concrete things (car,
  toilet, passport), not only proper names (prompt `v3`, whole vault
  re-extracted with `--force`).
- v1.2 (2026-10-05): `score`, `score-facet`, `score-parts`, `score-unsure`
  from the Jev scorer; `Facets.md` in the vault root; `Ranked` view.
- v1.3 (2026-10-05): `priority` removed; `score` replaces it (☆ no longer
  mapped). Existing thoughts stripped of the field.
- v1.4 (2026-10-05): `Contexts/` notes, `contexts` on thoughts, `Dashboard.md`.
- v1.5 (2026-10-06): universal `dealt-with` lifecycle, manual closure CLI,
  pooled sanitized OpenCode transcripts, session/repository/project graph, and
  evidence-backed review-only reconciliation pilot.
