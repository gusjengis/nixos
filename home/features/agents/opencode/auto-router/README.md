# Auto model router

Picks the model and reasoning effort per prompt, so routine turns stop running
on the most expensive model available.

Select **Auto** in `/models` (it is also the default model). From then on every
prompt is classified and sent to the cheapest model judged able to handle it.

```
Build · Claude Sonnet 5 Anthropic                     Auto Claude Sonnet 5 · auto
```

The right-hand label is this router. `Auto` means routing is active, then the
model the turn actually went to, its tier, then its effort. `auto` as an effort
means the model is choosing its own thinking budget.

A `?` after the tier — `(medium?)`, in warning colour — means the classifier was
unreachable and the keyword fallback picked that tier. The router still routes,
but it is guessing, and that should not look the same as knowing.

## Tiers

| Tier        | For                                                       | Model pool (ordered by intelligence)          |
| ----------- | --------------------------------------------------------- | --------------------------------------------- |
| `trivial`   | greetings, acknowledgements, trivia — turns asking for nothing | Claude Haiku 4.5 (15) · GPT-5.6 Luna (16) |
| `simple`    | small, well-specified edits and lookups                    | GPT-5.6 Luna (16) · Claude Haiku 4.5 (15)    |
| `medium`    | ordinary feature work                                      | GPT-5.6 Sol (34) · Claude Sonnet 5 (25)      |
| `complex`   | multi-file work, restructuring, non-obvious debugging      | GPT-5.6 Sol (39) · Claude Sonnet 5 (38)      |
| `reasoning` | architecture, concurrency, security, root-cause analysis   | Claude Opus 5 (48) · GPT-5.6 Sol (42)        |

`trivial` is deliberately narrow: a turn only lands there if it is
short, has no attachments, and asks for no work on the repository. Those turns
are not cheap ones — by the end of a long session they carry the whole
accumulated context — but they are ones a lightweight model handles efficiently.

Override a single prompt with `!free`, `!fast`, `!medium`, `!complex` or
`!deep`. The directive is stripped before the model sees it.

## How a tier is chosen

A small model held resident on `omega`'s GPU grades every turn. `RUBRIC.md` is
the definition of what the tiers mean; everything here implements it.

The grader is asked for two things and nothing else:

```json
{ "rule": "unknown_cause", "difficulty": "7" }
```

Both fields are constrained by a JSON schema server-side, so the shape cannot
drift. `rule` is one of seventeen named cases — `mechanical_edit`,
`pattern_feature`, `unknown_cause`, `correctness_critical` and so on — each
carrying the difficulty band it usually lands in. Naming the rule before the
number is chain-of-thought with no prose in it: it costs four tokens rather
than two hundred, it stops the model grading on vibes, and it makes every
decision auditable afterwards.

`difficulty` is read from its **logprobs**, not from the digit the sampler
picked. The probability-weighted mean over all nine digits turns a coarse label
into a continuous value, which is what makes the tier boundaries meaningful
rather than cosmetic. Boundaries live in `auto-router.json`, so recalibrating
the router is an edit, not a retrain.

Each rule's band sits wholly inside one tier, so the boundaries are the
midpoints between bands rather than numbers fitted to a sample:

| difficulty | tier | rules in this band |
| --- | --- | --- |
| 1 | `trivial` | `no_work` |
| 2-3 | `simple` | `direct_answer`, `mechanical_edit`, `run_command`, `stated_fix` |
| 4-5 | `medium` | `explain_code`, `pattern_feature`, `research_gather`, `multi_file_change` |
| 6-7 | `complex` | `new_component`, `unknown_cause`, `ambiguous_requirements`, `unfamiliar_integration` |
| 8-9 | `reasoning` | `open_ended_design`, `intermittent_defect`, `correctness_critical` |

The prompt is built against the known failure modes of LLM judges rather than
written from scratch. It says in as many words that length is not difficulty,
that a pasted stack trace is a *stated* cause and therefore easy, that being
about code is not difficulty, that touching many files is not by itself hard,
and that tone is not difficulty. Long prompts get their middle cut out and only
the ends sent, because volume reads as difficulty to a grader and the ask is
almost always at one end or the other.

A turn the grader marks `continuation` — "hit it", "still doing it", "my bad,
go ahead" — carries no difficulty of its own and inherits the session's tier
instead. Grading those on their own four characters is how a hard task silently
falls off the strong model on the word "yes".

Prior art this follows, rather than a design invented here: NVIDIA NeMo
Switchyard for the named-rule-then-number shape and for forecasting a number
that a deterministic policy thresholds outside the model, RouteLLM for the same
structure expressed as a win probability, and G-Eval for reading the score off
the logprobs instead of the sampled token.

### When omega is unreachable

Then `classify.js` runs instead: the original weighted keyword score, no network
call, no added latency. It is measurably worse, and the status line says so by
appending `?` to the tier. Failures trip a breaker that backs off geometrically
from 30 seconds to 10 minutes, so a laptop off the tailnet pays the connect
timeout once rather than on every prompt.

### Measured

190 graded prompts: 150 real turns sampled from this machine's own OpenCode
history, stratified by length, plus 40 written for the corners that real traffic
is too thin to cover. Both graded against `RUBRIC.md`. Reproduce with
`node eval/run.js`.

| | exact | balanced exact | within one tier | off by two or more | bias |
| --- | --- | --- | --- | --- | --- |
| keyword scorer | 30.0% | 33.9% | 79.5% | 20.5% | −0.68 tiers |
| `qwen3:4b-instruct-2507-q8_0` | 58.9% | 60.6% | 94.2% | 5.8% | +0.07 tiers |

`balanced exact` averages per gold tier instead of per prompt, so the rare tiers
count as much as `medium` does. Median added latency is 609 ms, p90 791 ms,
p99 1005 ms.

One deployment detail is load-bearing: the classifier must not send `num_ctx`.
Ollama keys the loaded runner on the context length, so a request that disagrees
with the length the model was loaded under evicts and reloads it — 2.4 s against
300 ms. The context window is set once, server-side, by
`OLLAMA_CONTEXT_LENGTH` in `ollama.nix`.

`bias` is the mean signed tier error. The keyword scorer is not merely
inaccurate, it is *consistently cheap* — it under-graded by two thirds of a tier
on average, which is exactly the complaint that prompted this: a long, detailed
prompt asking for a whole monitoring dashboard came out `medium`. It now comes
out `reasoning`.

Two larger models were measured on the same set and rejected.
`qwen3:30b-a3b-instruct-2507` graded 42 of 75 `medium` turns as `complex`, which
would send routine work to expensive models. `granite4.2:8b` is a thinking model
and spends its token budget reasoning before emitting the JSON, so it never
produced a parseable verdict.

Once a tier is chosen, models within that tier are ranked by:
1. **Intelligence score** (primary) — higher benchmark intelligence wins, to prioritize output quality
2. **Proven track record** — models that have answered in this session before
3. **Subscription headroom** — models with more remaining usage budget
4. **Stable hash** — ties broken predictably per session, so cache stays warm

The fallback scorer follows [LiteLLM's complexity
router](https://docs.litellm.ai/docs/proxy/auto_routing), including scoring the
last real human ask rather than the whole payload, stripping `<system-reminder>`
blocks first, and escalating on two or more reasoning markers.

LiteLLM itself is not used. It is a proxy, and routing this machine through it
would mean swapping the Anthropic and ChatGPT subscription logins for metered
API keys — turning a flat monthly cost into per-token billing, which is the
opposite of the point. The same argument is why the grader is local: a hosted
judge is a per-turn charge on every prompt, and published deployments measure it
at about a fifth of the whole routed bill. On owned hardware it is free, which
is the only reason grading every single turn is affordable at all.

## Model selection within a tier

Within each tier's pool, models are ranked by intelligence score (Artificial Analysis Intelligence Index v4.3, Sept 2026) rather than subscription headroom. This prioritizes output quality over cost distribution. Headroom still matters, but only to break ties between models with similar intelligence, or when the primary model is exhausted.

**Why intelligence-first?** Your router exists to save token spend by routing cheap turns away from expensive models. But cheap turns still need quality output — a weak model's wrong answer costs more in re-asks than running the right model would. Intelligence score therefore comes first to ensure every tier gets the smartest model available, with provider diversity maintained only as a fallback.

Stability rules that matter alongside intelligence prioritization:

- **Approvals inherit.** "yes, do it" runs at the tier that proposed the work.
- **Acknowledgements run free** and do not move the session's tier, so "thanks"
  after a hard turn costs nothing and the next real turn resumes where it was.
- **De-escalation drops one tier per turn.** Switching models throws away the
  provider-side prompt cache, and a cache rewrite can cost more than the cheaper
  rate saves.
- **Top-quality pool choices are sticky per session**, for the same reason. A
  lower-scoring fallback is replaced when the preferred model becomes usable.
- **State survives a restart** via the status file, so a resumed session keeps
  its tier instead of silently falling to the bottom.

## Broken models

A model that answers a routed turn with a fatal error - gone, unsupported on
these credentials, no such model - is quarantined: taken out of every pool for
an hour, doubling on each repeat strike up to a week. The record is written to
the status file, so it is shared by every running OpenCode and survives a
restart. Transient failures are excluded on purpose: rate limits, overload,
timeouts and auth problems say nothing about whether the model works.

If quarantine empties a tier, the turn routes *up* to the next tier rather than
failing. A cheap turn on an expensive model is the right way to lose here.

Ranking also prefers a model that has answered before, so an expiring
quarantine does not immediately put a dead model back in front of a working
one. Success is recorded when a routed session goes idle.

This is worth having because OpenCode decides whether to retry by
pattern-matching the error text, and OpenCode Zen reports an upstream 404 as
`Provider returned error`, which matches its retryable patterns. A permanently
dead model therefore burns the full five-attempt backoff - about seventy
seconds - rather than failing once.

That first stall cannot be avoided from a plugin: `session.error` is only
delivered after the retries are exhausted, the per-attempt events are internal
to the TUI, and no hook can change the model of an in-flight turn. What the
quarantine buys is that it happens once per model rather than once per prompt.

To rule a model out permanently, put it in `blocked` in `auto-router.json`.

## Subscription awareness

Headroom is read from the usage cache `quickshell-ai-usage` already maintains
for the bar widget. Within a tier the provider with more left wins, and a
provider under `avoidBelowHeadroom` percent is skipped when another candidate
has more room. A provider at zero is always excluded; if every subscription in
the pool is low, a non-zero candidate is used rather than restoring an exhausted
one.

If the active ChatGPT account is spent and the other saved account has
meaningfully more left, the router runs `quickshell-ai-account select` at
startup. It only does this at startup because OpenCode's OpenAI provider reads
`auth.json` once, in its auth loader, and then closes over that token for the
life of the process — a mid-session swap would not take effect. After startup
the router just stops routing to the exhausted provider, which works live.

## Files

| File                     | Role                                                        |
| ------------------------ | ----------------------------------------------------------- |
| `auto-router.js`         | Server plugin. Rewrites the model per turn.                 |
| `classifier.js`          | The grader: rules, prompt, Ollama client, breaker.          |
| `RUBRIC.md`              | What the tiers mean. The contract the rest is measured against. |
| `classify.js`            | Offline keyword scorer. Fallback only. Pure, no I/O.        |
| `usage.js`               | Headroom and ChatGPT account switching.                     |
| `auto-router.json`       | Tunables. Merged over the defaults in `auto-router.js`.     |
| `eval/run.js`            | Measures a model against the graded set.                    |
| `eval/gold_*.json`       | The graded prompts.                                         |
| `../tui-plugins/auto-router-status.tsx` | The status label.                            |

The grader itself is deployed by `system/modules/software/ollama.nix`, enabled
on `omega` only. It pins the model in VRAM with `keep_alive: -1`, re-warms it on
a timer in case the daemon restarts, and opens port 11434 on the `tailscale0`
interface alone — Ollama has no authentication, so it must never be reachable
from the LAN.

Re-measure after changing the prompt, the rules or the bands:

```
node eval/run.js                      # the configured model
node eval/run.js --heuristic          # the fallback, for comparison
node eval/run.js --model <tag> --tune # try another model, fit boundaries
```

`--tune` reports held-out numbers from five-fold cross-validation, because
boundaries fitted and scored on the same prompts flatter themselves.

Routing state, the quarantine and per-model health are written to
`~/.local/state/opencode/auto-router.json`. Every decision is logged with its
score and signals:

```
rg 'routing decision|quarantined' ~/.local/share/opencode/log/opencode.log
```

Agent colours are pinned in `opencode.json` rather than left to OpenCode's
defaults. An agent without an explicit `color` gets the theme colour at its
index in the agent list, so defining `deep` and `quick` renamed every colour
after them alphabetically and moved plan mode from yellow to blue - which the
tmux status line mirrors.

## Implementation note

`chat.message` fires after OpenCode builds the user message but before it
persists it. The router classifies the prompt, picks a tier, selects the best
model from that tier's pool, and rewrites `output.message.model` to redirect
the turn. The session loop later reads this model from the persisted message.

The TUI re-reads the model from the last user message when a session comes into
view, so shortly after the first routed turn the visible selection stops saying
"Auto" and starts naming the concrete model. Later prompts then arrive already
bound to it. The router treats a prompt that arrives on exactly the model it last
routed that session as still being in Auto, and keeps routing; anything else is
read as a deliberate choice and turns routing off for that session. Re-select
**Auto** in `/models` to turn it back on.

## Turning it off

Set `"enabled": false` in `auto-router.json`, or just pick a real model in
`/models`.
