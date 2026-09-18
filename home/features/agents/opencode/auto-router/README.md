# Auto Model Router

## Abstract

Auto chooses a model and reasoning effort for OpenCode without replacing your
Anthropic or OpenAI subscription logins with paid API keys. A small local model
estimates task difficulty; deterministic rules protect ongoing work, account
quota, and failed models. Once a conversation needs a stronger model, Auto keeps
that working tier instead of switching to a cheaper model for every short reply.
When the active saved OpenAI account runs out, Auto can select the other saved
account before the next routed turn. This uses the same account switch as the
Quickshell widget and works without restarting OpenCode's normal HTTP transport.
The goal is reliable work with less wasted usage. Actual net savings have not
been measured; a paid A/B experiment is explicitly deferred.

## Everyday Use

Select **Auto** in `/models`. It is also the configured default.

Start a new session for an unrelated task. Within a session, shorter prompts do
not automatically mean easier work: "yes", "thanks", and a small follow-up stay
at the working tier. Harder requests can raise it immediately.

Use a directive when you deliberately want a different tier:

| Directive | Effect |
| --- | --- |
| `!fast` or `!simple` | Lightweight work; explicitly lowers an expensive session |
| `!medium` | Routine implementation or explanation |
| `!complex` | Investigation, integration, or design decisions |
| `!deep` or `!reasoning` | Hard or correctness-critical work |
| `!trivial` | Smallest tier |

The directive is removed before the model sees the prompt. It establishes the
new working tier, not merely a one-turn discount. Legacy aliases `!cheap`,
`!mid`, `!hard`, `!max`, and `!free` also work. **`!free` is not actually free**:
the trivial pool uses subscriptions.

Choosing a different concrete model turns Auto off for that session. Reselect
Auto to enable it. Because OpenCode displays the last routed model, the plugin
cannot distinguish deliberately selecting that *same* model from leaving Auto
active. To disable routing unambiguously, select a different model or disable
the plugin and restart.

## Request Flow

```text
User submits a prompt with Auto active
  -> read current account identity and subscription usage
  -> if active OpenAI account is exhausted, await eligible account switch
  -> recognize directive, retry, approval, or acknowledgement
  -> otherwise ask local classifier; use keyword fallback if unavailable
  -> apply attachment, work, and session-continuity safeguards
  -> find an available model with usable subscription headroom
  -> choose reasoning effort and rewrite the message's model
  -> OpenCode sends the request using its normal provider integration
  -> record the decision for logs and the TUI status label
```

This happens in OpenCode's `chat.message` hook, before the user message is
persisted. The session loop reads the rewritten `message.model` afterward.
`auto/auto` is a placeholder with an intentionally unusable endpoint, not a
proxy. If no usable model remains, the plugin raises a clear error rather than
letting that placeholder reach the network.

## Difficulty And Models

| Tier | Typical work | Configured pool |
| --- | --- | --- |
| `trivial` | Greetings and standalone acknowledgements | Haiku 4.5, GPT-5.6 Luna-fast |
| `simple` | Mechanical edits and bounded lookups | GPT-5.6 Luna-fast, Haiku 4.5 |
| `medium` | Routine features and focused explanations | GPT-5.6 Sol-fast, Sonnet 5 |
| `complex` | Unknown causes, new components, integrations | GPT-5.6 Sol, Sonnet 5 |
| `reasoning` | Concurrency, security, difficult design | Opus 5, GPT-5.6 Sol |

Trivial and simple currently share models and effort. Their distinction is
semantic, not a guaranteed difference in consumption.

The local classifier is `qwen3:4b-instruct-2507-q8_0` on `omega:11434`. It sees
the current user's text and attachment count, not the full conversation, file
contents, or tool results. Long text keeps its first 3,000 and last 1,500
characters. Synthetic text and complete system-reminder blocks are excluded.

It returns a named rule and difficulty from 1 to 9. When digit log-probabilities
are available, the router computes a probability-weighted score. Otherwise it
uses the emitted digit. This smooths grading; it is **not** a measured probability
that a target model will solve the task.

Tier boundaries are 1.5, 3.5, 5.5, and 8.0. The rubric lives in `RUBRIC.md`.
A stack trace is treated as a symptom, not automatically as proof of an easy
fix. An established cause and obvious correction can still be simple.

The classifier has a 3-second timeout, a 256-entry in-memory result cache, and
a circuit breaker. Two transport failures open the breaker for 30 seconds;
repeated failures increase that pause up to 10 minutes. While unavailable,
weighted keywords choose the tier. No hosted classification call is made.
Local inference still consumes hardware resources and adds latency.

## Continuity And Selection

Safety rules run before or after grading as appropriate:

- Whole-message approvals inherit the working tier, or medium when no history exists.
- Whole-message acknowledgements retain the working tier, or trivial in a new session.
- "Thanks, fix the auth bug" is work, not an acknowledgement shortcut.
- Attachments bypass acknowledgement/approval shortcuts and impose at least medium, unless explicitly overridden by a directive.
- Recognized failed-work replies such as "try again" or "still broken" raise the prior tier by one, capped at reasoning.
- Other short replies cannot lower the working tier by default: `maxDropPerTurn` is zero.
- Explicit directives can lower the tier. Starting a new session also starts fresh.

Preserving the model gives provider-side prompt caching a better chance to help.
It does not guarantee a cache hit: expiry, account changes, prompt changes, and
provider behavior still matter. Keeping a strong model also consumes its output
and reasoning budget; this is a continuity policy, not a proven cost optimum.

Within the chosen tier, selection works as follows:

1. Remove models absent from a successfully loaded catalog, blocked models,
   quarantined models, and providers with known zero headroom.
2. If none remain, search higher tiers. Finally try the configured Sonnet fallback
   under the same eligibility checks. If that also fails, report an error.
3. Prefer candidates above 8% headroom when available. A positive but low budget
   remains usable if no better-budget candidate exists. Unknown quota is not zero.
4. Keep models within `intelligenceTolerance` (currently two benchmark points)
   of the best eligible model. Scores are static policy inputs, not task-specific proof.
5. Keep the session's existing pick if still eligible within that group.
6. Otherwise prefer proven health, then headroom, then exact score, then a stable tie-break.

Reasoning effort is none for trivial/simple and low for medium when supported.
Complex/reasoning use adaptive defaults on detected adaptive Anthropic models;
other models use medium/high respectively. Unsupported variants are omitted.
A variant explicitly selected on the Auto entry overrides the tier for that turn.

## Both OpenAI Accounts

The router uses the existing saved `personal` and `business` profiles. It does
not create accounts, copy credentials into router state, or automatically save
a new login. Save/reconnect profiles through the existing widget workflow.

Before every Auto-routed turn, `usage.js` asks `quickshell-ai-account status`
which saved profile actually matches OpenCode's current credentials. This
returns profile names only, not tokens. Cached widget `active` flags are not
trusted as account identity.

Usage comes from `~/.local/state/quickshell/ai-usage.json`. Headroom is
`100 - max(window usage)`: either the short or weekly window can exhaust an
account. These are provider percentages, not token counts, and currently rounded
by the helper. Missing, failed, too-old, or reset-expired observations are unknown.
An elapsed reset does not invent a fresh 100% budget.

Missing/stale observations trigger an awaited `quickshell-ai-usage` refresh,
which polls both saved accounts and Anthropic. Ordinary unsuccessful refreshes
are throttled to one attempt per minute per plugin instance. An OpenAI quota or
rate-limit error requests a refresh before the next routed turn, bypassing that
cooldown. It does not treat every rate-limit error as account exhaustion.

When active usage is 100% and another saved account has fresh positive headroom:

1. Choose the alternate with the most remaining headroom.
2. Await `quickshell-ai-account select <alternate> <expected-active>`.
3. The helper checks the expected active profile under its existing account lock,
   so a stale decision does not undo a widget or other helper switch.
4. Use the returned active identity immediately for model selection, without
   waiting for the widget cache to change its active flags.

Even **1% remaining qualifies**. There is no 90%-used preemptive switch or
20-point minimum gain anymore. If both accounts are exhausted, use an eligible
Anthropic model or report no usable model. A failed selection is followed by
an identity check rather than assuming it succeeded.

Normal turns use cached usage plus a local status command. An exceptional refresh
can wait up to 45 seconds; selection up to 30 seconds; status up to 5 seconds.
These are helper limits, separate from the classifier's 3-second budget.

### Live Switching Limits

Installed OpenCode's OAuth HTTP transport rereads credentials for every request.
Switching accounts therefore needs **no OpenCode restart**. Selection is global,
just like the widget: another pane's next HTTP request can see the new account.
The plugin does not establish a global idle barrier across running sessions.

The switch is attempted before a new routed prompt, not by replaying an in-flight
turn or its tool actions. A failure occurring partway through a turn can still
reach the user; the next routed turn can refresh quota and switch. Explicitly
pinned agents/models bypass Auto's per-turn selection policy.

Experimental persistent WebSocket transport and `OPENCODE_AUTH_CONTENT` are
exceptions to normal live file-based switching. Existing authenticated sockets
may retain an old account, and the auth environment override takes precedence
over the file. Keep normal HTTP/file-backed OAuth for this setup.

The helper lock coordinates Quickshell commands, not OpenCode's own token refresh
writes. It reduces helper races but is not full cross-process credential isolation.
Widget cards refresh on their own polling/open workflow; an automatic switch
need not immediately repaint an already-open card.

## Errors And Visibility

Fatal model errors can quarantine a model for one hour, doubling repeated strikes
up to one week. Rate limits, network errors, and authentication problems do not
prove a model is broken and are excluded. Blocked and quarantined models are not
silently reinstated as a last resort. A turn reporting an error is not marked
healthy merely because its session later becomes idle.

Quarantine applies to later turns. The plugin does not replace OpenCode's
in-flight retry machinery. Successful idle without a reported error is only an
operational health signal, not proof that an answer was correct.

The TUI status label shows Auto, chosen model/tier, and effort. A question mark
on heuristic-classified work indicates fallback grading. Decisions, including
OpenAI profile when known, are logged and written to
`~/.local/state/opencode/auto-router.json`. The file retains at most 64 recent
session entries plus model health and quarantine. It is a current snapshot,
not a complete usage ledger. Atomic replacement prevents partial JSON reads;
independent processes can still race on whole-file updates.

## Other Agents

`quick` is a read-only lookup agent pinned to GPT-5.6 Luna-fast. It cannot edit or
run shell commands. It consumes OpenAI subscription quota; use direct reads when
delegating would add more context than it saves. Title generation uses the same
model. These replaced a free provider that rejected calls during review.

`deep` remains pinned to Opus 5 for bounded difficult subproblems. An explicit
agent model is not another Auto tier. Delegation duplicates some context, so
reserve it for useful isolation or genuine complexity.

## Files And Deployment

| File | Responsibility |
| --- | --- |
| `auto-router.js` | Hook, tier safeguards, candidate selection, state and errors |
| `auto-router.json` | Pools, effort, thresholds, quota and continuity settings |
| `classifier.js` | Local grading prompt, Ollama request, cache and breaker |
| `classify.js` | Pure text rules and offline heuristic |
| `usage.js` | Usage freshness, active identity, awaited account failover |
| `RUBRIC.md` | Intended difficulty categories |
| `router.test.js`, `usage.test.js` | Offline regression tests with mocks |
| `eval/run.js`, `eval/gold_*.json` | Classifier agreement evaluation |
| `../opencode.json` | Auto placeholder and pinned agents |
| `../tui-plugins/auto-router-status.tsx` | Status display |
| `../../../desktop/quickshell/usage.py` | Shared usage/account helper |

Home Manager links the plugin entrypoint and OpenCode configuration back into
this repository. Its sibling modules load from here. Quickshell command wrappers
also point at the repository's helper. These edits need no Nix rebuild on the
already-linked machine. Restart OpenCode once to load changed plugin/config code;
subsequent account switches do not require restarts.

The local classifier is deployed by `system/modules/software/ollama.nix` on
omega. Its context length is configured server-side; the client deliberately
does not send `num_ctx`, avoiding runner reloads from mismatched context sizes.
Ollama's unauthenticated port must remain restricted to the intended Tailnet.

## Verification

From `/etc/nixos`, offline tests do not call models, fetch quota, or switch real accounts:

```bash
node --test home/features/agents/opencode/auto-router/router.test.js home/features/agents/opencode/auto-router/usage.test.js
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s home/features/desktop/quickshell -p test_usage.py
```

The classifier evaluation uses 150 historical prompts and 40 probes. It measures
agreement with assigned tiers, not completed-task quality or subscription savings.
Its `cost` statistic is weighted tier distance. Five-fold tuning holds out prompts
for threshold fitting, but does not validate the whole routing system. Fixtures
do not simulate conversation continuity, accounts, or actual target-model work.
Historical accuracy numbers predate the revised diagnostic rules and are not
current guarantees.

These commands are optional, not automatic:

```bash
node home/features/agents/opencode/auto-router/eval/run.js --heuristic
node home/features/agents/opencode/auto-router/eval/run.js
```

The first is offline. The second calls the local classifier, not paid target
models. Neither performs a paid-model A/B experiment.

## Deferred Savings Study

Do not run a paid comparison without explicit approval. A future study could
compare Auto with a fixed capable-model baseline on equivalent representative
tasks, measuring correctness, corrective turns, total input/output/reasoning
tokens, cache reads/writes, latency, and subscription consumption where exposed.
Keep evaluation tasks separate from threshold tuning and count failed attempts
and delegation overhead. Optimize usage per successfully completed task, not
cheapness per individual turn. No such experiment is enabled or scheduled.

## Deferred Context-Aware Routing

Potential future improvement: run a bounded, isolated read-only scout before
final classification when the prompt lacks repository context. The scout could
use Qwen on omega, inspect a few relevant files with glob/grep/read, and return
paths, brief evidence, and uncertainties. The final classifier could then
distinguish routine pattern work from unfamiliar integration or high-risk
changes, while the selected model could reuse the evidence.

Do not make Qwen the active conversation model for scouting. Keep reconnaissance
outside the conversation to avoid tool-call history, model handoff artifacts,
unbounded investigation, and accidental edits. Skip scouting for directives,
continuations, obvious mechanical requests, and prompts with sufficient context.
Enforce read-only tools, strict call/output/time limits, and conservative
fallback on timeout or uncertainty. Context must be structured evidence, not a
large file dump. This idea needs separate latency, routing-quality, and total
usage measurement before implementation; it is noted only and currently
disabled.
