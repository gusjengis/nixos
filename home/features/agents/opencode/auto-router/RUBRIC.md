# Prompt difficulty rubric

The single definition of what each tier means. Three things read it and they
must agree, or the router cannot be evaluated at all:

- `classifier.js` renders it into the system prompt sent to the local model.
- `eval/gold_real.json` and `eval/gold_probes.json` contain prompts graded against it.
- `classify.js`, the offline heuristic, approximates it with keywords.

## The question being answered

> A competent mid-tier coding agent is given this turn, with full tool access,
> in this repository, and one attempt. How likely is it to finish correctly
> without a stronger model having to redo the work?

Difficulty is that probability inverted. It is **not** how long the prompt is,
how much code it contains, or how important it feels.

## Tiers

| Tier | Meaning |
| --- | --- |
| `trivial` | Asks for nothing. Greeting, thanks, acknowledgement, or a one-line fact needing no lookup. |
| `simple` | One obvious mechanical action. The location is stated or trivially findable, and there is no judgement call: fix a typo, rename a symbol, add a comment, run a named command, answer a direct question about a named file. |
| `medium` | Routine work with a clear approach. A small feature that follows a pattern already in the repository, a localized fix where the symptom is stated, a config change over a couple of files, a focused explanation of existing code. |
| `complex` | Several files, or a real design decision, or a cause that has to be found. New component, cross-module refactor, integrating an unfamiliar API, diagnosing a failure whose cause is not given. |
| `reasoning` | Correctness-critical or open-ended. Concurrency, security, data migration, performance work, protocol design; ambiguous or self-contradictory requirements; large redesigns; root-causing subtle behaviour; anything where a plausible wrong answer is expensive to discover later. |

## Rules that decide the hard cases

These exist because each one is a documented failure mode of LLM routers.

1. **Grade the hardest requirement, not the average one.** A turn with nine
   trivial asks and one genuinely hard one is as hard as the hard one.

2. **Length is not difficulty.** Pasted logs, stack traces, file dumps and long
   background sections inflate a prompt without making the task harder. This is
   verbosity bias and it is the most common way a judge gets this wrong.

3. **Specification makes a task easier, not harder.** A long prompt that names
   the files, states the desired behaviour and gives a command to verify it is
   *easier* than a one-line prompt that does not. Do not read "detailed" as
   "hard". Conversely a short prompt can be the hardest kind: *"make the
   scheduler lock-free"* is five words.

4. **Being about code is not difficulty.** Routers reliably collapse into
   sending every coding turn to the strongest model, which saves nothing. Most
   coding turns are `simple` or `medium`.

5. **Unknown cause outranks known cause.** "Fix the null check on line 40" is
   `simple`. "It crashes sometimes and I don't know why" is at least `complex`,
   and `reasoning` if the symptom is intermittent, timing-dependent or
   environment-dependent.

   A stack trace identifies where a failure appeared, not necessarily its cause.
   Use `stated_fix` only when the cause and correction are established. Merely
   pasting an error must not downgrade an investigation.

6. **Ambiguity is difficulty.** If the turn can be read two reasonable ways and
   nothing in it decides between them, the agent has to choose, and choosing
   wrong wastes the whole turn.

7. **Irreversible or wide blast radius raises the tier by one.** Deleting data,
   rewriting history, changing authentication, editing a migration, touching
   something every machine in the fleet depends on.

8. **Judge the ask, not the tone.** Frustration ("this is still broken!!") is
   not difficulty. Politeness is not simplicity.

9. **Research and open-ended search are at least `medium`.** Going out to find
   things, compare options, or gather sources is multi-step work even when each
   step is easy.

## Calibration anchors

| Prompt | Tier | Why |
| --- | --- | --- |
| "thanks, that worked" | `trivial` | asks for nothing |
| "please clean up warnings" | `simple` | mechanical, compiler says where |
| "add a comment explaining this regex" | `simple` | one edit, no judgement |
| "yes, find the link to the latest episode and open it with chromium" | `medium` | small multi-step, approach obvious |
| "make the ring rendering dim all parts of the ring that have already passed today" | `medium` | one component, clear behaviour, existing pattern |
| "I want to run rehome every time my computer boots, the first time it connects to the network" | `complex` | needs a unit, an ordering decision and a once-per-boot guard |
| "build a dashboard that monitors every Linux device on my tailnet: live CPU/memory/disk, per-host service health, alerts" | `complex` | new subsystem, several components, design decisions throughout |
| "the widget opens a new Chromium tab instead of controlling the running player" | `complex` | cause not stated, needs investigation |
| "migrate the state file format and keep old sessions readable" | `reasoning` | migration, irreversible, compatibility constraint |
| "the scheduler deadlocks under load, find out why" | `reasoning` | concurrency, unknown cause, intermittent |
