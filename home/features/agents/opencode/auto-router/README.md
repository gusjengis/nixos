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

| Tier        | For                                                       | Default models                                |
| ----------- | --------------------------------------------------------- | --------------------------------------------- |
| `trivial`   | greetings, acknowledgements, trivia — turns asking for nothing | OpenCode Zen free models                  |
| `simple`    | small, well-specified edits and lookups                    | Claude Haiku 4.5 · GPT-5.6 Luna Fast          |
| `medium`    | ordinary feature work                                      | Claude Sonnet 4.5 · GPT-5.6 Sol Fast          |
| `complex`   | multi-file work, restructuring, non-obvious debugging      | Claude Sonnet 5 · GPT-5.6 Terra               |
| `reasoning` | architecture, concurrency, security, root-cause analysis   | Claude Opus 5 · GPT-5.6 Sol                   |

`trivial` is free but deliberately narrow: a turn only lands there if it is
short, has no attachments, and asks for no work on the repository. Those turns
are not cheap ones — by the end of a long session they carry the whole
accumulated context — but they are ones a weak model cannot get meaningfully
wrong.

Override a single prompt with `!free`, `!fast`, `!medium`, `!complex` or
`!deep`. The directive is stripped before the model sees it.

## How a tier is chosen

No classifier model, no network call, no added latency. A weighted score across
eight dimensions — length, code presence, reasoning markers, technical terms,
conversational markers, build intent, multi-step structure, question complexity
— is cut into tiers by `boundaries`. Keyword rules run first and can only
escalate, except where the scorer found nothing to say.

The design follows [LiteLLM's complexity
router](https://docs.litellm.ai/docs/proxy/auto_routing), including scoring the
last real human ask rather than the whole payload, stripping `<system-reminder>`
blocks first, and escalating on two or more reasoning markers.

LiteLLM itself is not used. It is a proxy, and routing this machine through it
would mean swapping the Anthropic and ChatGPT subscription logins for metered
API keys — turning a flat monthly cost into per-token billing, which is the
opposite of the point.

Stability rules that matter more than raw accuracy:

- **Approvals inherit.** "yes, do it" runs at the tier that proposed the work.
- **Acknowledgements run free** and do not move the session's tier, so "thanks"
  after a hard turn costs nothing and the next real turn resumes where it was.
- **De-escalation drops one tier per turn.** Switching models throws away the
  provider-side prompt cache, and a cache rewrite can cost more than the cheaper
  rate saves.
- **Pool choice is sticky per session**, for the same reason.
- **State survives a restart** via the status file, so a resumed session keeps
  its tier instead of silently falling to the bottom.

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

## Delegation

Two subagents, for opposite reasons.

`@quick` runs on a free model and is read-only. Handing it file reading,
searching and summarising is token-positive: its context is spent on the free
model, and the caller pays only for the task call and the summary that comes
back, instead of paying for every file it would otherwise pull into its own
window. Several can run in parallel.

`@deep` runs on the strongest model and costs real usage, so it is hard-capped
at 2 per turn and 6 per session. It exists so a cheap tier can buy reasoning for
one sub-problem without promoting the whole conversation.

Both budgets are enforced in `tool.execute.before`, not merely requested in the
prompt, because an unbounded delegation path costs more than never routing down.

Session titles are generated by a free model too (`agent.title` in
`opencode.json`); that ran on the conversation model before, once per session.

## Files

| File                     | Role                                                        |
| ------------------------ | ----------------------------------------------------------- |
| `auto-router.js`         | Server plugin. Rewrites the model, enforces budgets.        |
| `classify.js`            | Scorer and tier rules. Pure, no I/O.                        |
| `usage.js`               | Headroom and ChatGPT account switching.                     |
| `auto-router.json`       | Tunables. Merged over the defaults in `auto-router.js`.     |
| `../tui-plugins/auto-router-status.tsx` | The status label.                            |

Routing state is written to `~/.local/state/opencode/auto-router.json`. Every
decision is logged with its score and signals:

```
rg 'routing decision' ~/.local/share/opencode/log/opencode.log
```

## Implementation note

`chat.message` fires after OpenCode builds the user message but before it
persists it, and the session loop later reads the model off that persisted
message. Mutating `output.message.model` in the hook is therefore enough to
redirect the turn.

One consequence leaks into the UI. The TUI re-reads the model from the last user
message when a session comes into view, so shortly after the first routed turn
the visible selection stops saying "Auto" and starts naming the concrete model.
Later prompts then arrive already bound to it. The router treats a prompt that
arrives on exactly the model it last routed that session as still being in Auto,
and keeps routing; anything else is read as a deliberate choice and turns
routing off for that session. Re-select **Auto** in `/models` to turn it back
on.

## Turning it off

Set `"enabled": false` in `auto-router.json`, or just pick a real model in
`/models`.
