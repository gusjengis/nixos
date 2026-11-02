# OpenCode speed/reliability acceptance

Harness: `home/features/desktop/contexts/opencode_acceptance_fixture.py` and
`test_opencode_acceptance.py`. Each fixture is one isolated "device": private
HOME/XDG/runtime, native database, context root, work root and scope/state files
under `/tmp/opencode/oc1-acceptance-*`. No production profile, credentials or
tmux session is used. The installed immutable session-policy guard is loaded
read-only when present.

What is measured is real behavior, not prompt rendering:

- Native TUI in a PTY, rendered through a cursor-addressed VT screen model
  (erased composer text does not count).
- Submission is proven by the TUI's own message state, plus a distinct unsent
  draft rendered below the submitted message.
- Dispatch is proven by a loopback OpenAI-compatible provider recording the
  request. It holds its response until assertions finish; no response may
  render during the 2s hold.
- Background discovery (`opencode-context-chats prepare`) can be held open
  indefinitely. Fresh and unchanged sends must reach the provider while it is held.
- Other library commands run the real `context_chat_library.py` CLI.
- Two-device scenarios move only portable archive bytes from A to B, never the
  native database or ledger.

## Commands

```sh
cd home/features/desktop/contexts
python3 -B -m unittest test_opencode_acceptance            # screen-model unit only
# Installed/pinned binary:
OPENCODE_ACCEPTANCE_NATIVE=1 OPENCODE_ACCEPTANCE_BINARY=/nix/store/...-opencode-1.19.3+e3c4eb2/bin/opencode \
  python3 -B -m unittest test_opencode_acceptance -v
# Integrated binary (package.nix .native, sessions+freshness+stale patches);
# loads production TUI plugins context-library.tsx + context-stale.tsx:
OPENCODE_ACCEPTANCE_INTEGRATED=1 ...same...
# Paired warm benchmark (native vs launcher, same plugins, alternating order):
OPENCODE_ACCEPTANCE_BENCHMARK_PAIRS=20 ... -k test_paired_warm_performance
# Optional: OPENCODE_ACCEPTANCE_RESULTS=file.jsonl, OPENCODE_ACCEPTANCE_ENFORCE_TIMING=1
```

Behavior assertions always fail the test. Absolute timing budgets are enforced
only with `OPENCODE_ACCEPTANCE_ENFORCE_TIMING=1`, because shared, loaded build
machines make them noisy. The paired integration-overhead budget is always enforced.

## Thresholds

| Gate | Budget |
|---|---|
| Paired p95 launcher overhead over direct native, every metric | ≤500ms (enforced) |
| Launch → typed sentinel visible, warm p95 | ≤5s |
| Submit → submitted history + new draft rendered, p95 | ≤500ms |
| Submit → provider receipt, p95 | ≤1s |
| History picker → local + portable summaries | ≤1s |
| Remote delivery → stale state / blocking overlay | ≤5s |
| Known-stale, conflicting or unverified send | 0 provider requests, 0 persisted messages |
| Unselected portable conversations imported by list/select | 0 |

## Scenarios

| Test | Covers (owner) |
|---|---|
| `*_fresh_send_*` (native/launcher, held/unheld discovery) | Fresh first send with discovery held (OC2/OC5) |
| `unchanged_existing_chat_sends_while_preparation_blocked` | Current-as-known continuation with discovery held (OC5) |
| `created_here_chat_rechecks_new_revision_before_next_send` | No lifetime "created here" exemption (OC5/OC6) |
| `late_remote_update_blocks_send_on_received_copy` | A/B: update arrives after B opened the chat; real discovery marks it outdated; send blocked (OC2/OC5) |
| `two_isolated_devices_portable_list_selected_import_and_idempotence` | Index-only list, selected-family import, re-ensure without duplicates, full export (OC2/OC7) |
| `integrated_stale_overlay_blocks_and_opens_latest_with_draft` | Blocking overlay; Escape cannot dismiss; no silent switch; Enter opens latest verified copy; draft carried; old history kept (OC6) |
| `integrated_history_picker_lists_portable_and_opens_selected` | Native picker shows portable-only summaries; only the selected family is imported (OC4) |
| `paired_warm_performance` | Integration overhead and absolute budgets (OC1) |

Covered by owners' own suites, not repeated here: lock contention and coalescing
(OC3), crash/interruption recovery boundaries (OC7), Claude auth expiry and
account switching (OC8).

## Results, 2026-10-30, PC, isolated fixtures

Integrated binary `/nix/store/a8px816fa7n9sqyv4s73f8xsj9xaxfvr-opencode-1.19.3+e3c4eb2`,
built locally from the live worktree. Ran with production TUI plugins: 10 passed,
1 skipped (the benchmark, run separately). The same suite also passes on the
installed binary `ghvj6ri4…` with the live OC5 server plugin.

20 warm pairs, load average about 5:

| Metric | Native p95 | Launcher p95 | Paired p95 overhead |
|---|---|---|---|
| Launch → typing | 2431ms | 2352ms | +135ms |
| Submit → submitted message state | n/a | 482ms | +71ms |
| Submit → history + draft rendered | 516ms | 500.2ms | +75ms |
| Submit → provider receipt | 720ms | 668ms | +248ms |

- Integration ≤500ms: **pass**.
- Absolute ≤500ms rendered history: **marginal fail** (500.2ms). The direct native
  baseline also misses it (516ms), so this is upstream render cost.
- Continuation dispatch with discovery held: 29–43ms.
- Remote delivery → outdated state: 311–348ms.
- Remote delivery → blocking overlay: 131ms. Enter → latest verified copy: 4.1s
  (includes selected import).
- Picker → summaries: 149ms. Selection → ready: 2.65s.
- Cold-profile selected import (small history, CLI): about 8.1s, over the 5s budget.
  It includes first native database initialization in a fresh profile.

## Not yet proven

- Physical two-device sign-off, network loss, and reboot persistence. Only isolated
  A/B fixtures on one machine have run.
- Large (20MiB) histories, a 1,000-summary picker, and multiple simultaneous windows
  selecting the same conversation in the TUI.
- The integrated binary needs `context-stale.tsx` loaded. Without it, the stale
  host holds continuation drafts in the composer with no explanation. Activate the
  binary and `tui.json` together.
