# Second Brain Data Model (v1.1)

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

Everything below `Raw/` can be rebuilt from `Raw/`. Nothing is deleted
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
3. **Projects are notes, not tags.** A project is a thought with type
   `project`. Thoughts belonging to it link to it with `part-of`. One mechanism
   instead of two that drift apart; the project note's backlinks are its
   contents. (A project may still carry subject tags of its own.)
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
7. **Scope for now: captures only.** `TODOS.md`, older vault notes and Markdown
   from other repos are not imported yet. (Long term, repo docs will be pulled
   in for project context.)

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
| `status` | `todo` `doing` `waiting` `done` `dropped` `someday` (tasks only) | **user** after creation |
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
