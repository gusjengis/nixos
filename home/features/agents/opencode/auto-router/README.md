# Auto model router

Picks the model and reasoning effort per prompt, so routine turns stop running
on the most expensive model available.

Select **Auto** in `/models` (it is also the default model). From then on every
prompt is classified and sent to the cheapest model judged able to handle it.

```
Build · Claude Sonnet 5 Anthropic                     Auto Claude Sonnet 5 · auto
```

The right-hand label is this router. `Auto` means routing is active, then the
model the turn actually went to, then its effort. `auto` as an effort means the
model is choosing its own thinking budget.

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

No classifier model, no network call, no added latency. A weighted score across
eight dimensions — length, code presence, reasoning markers, technical terms,
conversational markers, build intent, multi-step structure, question complexity
— is cut into tiers by `boundaries`. Keyword rules run first and can only
escalate, except where the scorer found nothing to say.

Once a tier is chosen, models within that tier are ranked by:
1. **Intelligence score** (primary) — higher benchmark intelligence wins, to prioritize output quality
2. **Proven track record** — models that have answered in this session before
3. **Subscription headroom** — models with more remaining usage budget
4. **Stable hash** — ties broken predictably per session, so cache stays warm

The design follows [LiteLLM's complexity
router](https://docs.litellm.ai/docs/proxy/auto_routing), including scoring the
last real human ask rather than the whole payload, stripping `<system-reminder>`
blocks first, and escalating on two or more reasoning markers.

LiteLLM itself is not used. It is a proxy, and routing this machine through it
would mean swapping the Anthropic and ChatGPT subscription logins for metered
API keys — turning a flat monthly cost into per-token billing, which is the
opposite of the point.

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
provider under `avoidBelowHeadroom` percent is skipped entirely.

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
| `classify.js`            | Scorer and tier rules. Pure, no I/O.                        |
| `usage.js`               | Headroom and ChatGPT account switching.                     |
| `auto-router.json`       | Tunables. Merged over the defaults in `auto-router.js`.     |
| `../tui-plugins/auto-router-status.tsx` | The status label.                            |

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
