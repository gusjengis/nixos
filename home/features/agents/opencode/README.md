# OpenCode integration

Pinned OpenCode 1.19.3 carries context ownership/history, freshness and blocking
stale-session patches. The
launcher publishes local context visibility, then executes OpenCode without
checking network working directories or synchronizing chat histories.

## Startup

- `plugins/context-library.js` discovers visible portable summaries asynchronously.
  Fresh and unchanged local conversations send without waiting for discovery.
  Every send checks device-local authoritative freshness and received-head state;
  conversations created here have no lifetime exemption. Opening a portable-only
  conversation imports only its selected family. Preparation failures retain
  histories and report errors without turning missing data into readiness.
- The history picker merges local rows and portable summaries with persistent
  availability/progress/error state. `context-stale` blocks known superseded chats
  with an acknowledgement overlay, preserves drafts and histories, and opens the
   latest verified copy only after a deliberate choice and revision recheck.
   A changed shared archive head alone does not latch the stale overlay: discovery
   first determines whether this conversation changed. Local checkpoint publication
   is recognized through its database-local durable journal, including the interval
   before ledger commit; local selection and observed revision publish atomically.
- `notebook/` resolves notebook identity from conversation ownership using local
  metadata, without probing job/repository directories.
- `tui-plugins/context-persistence.js` exposes selected-chat metadata for terminal
  recovery. Its `db path` helper explicitly skips interactive startup preparation.
- `tmux-theme` copies theme colors into tmux pane options; it does not restore
  windows. `tmux-status` drives work/question/completion indicators.
- `session-notify` provides desktop notifications and sounds.
- The existing evening-policy plugin remains rebuild-controlled.

Default model is `openai/gpt-6.1-sol`. No automatic model router or custom
quick/deep agents. Main-vault transcript collector remains available manually;
its user and Omega system timers are declaratively omitted while that vault is
archived. Verify activation separately on each host.

## Claude authentication

`claude-auth.nix` pins upstream `opencode-claude-auth` 2.2.1 and applies
`claude-auth.patch`. Initialization reads local credentials and registers hooks;
it performs no credential refresh. First Anthropic request refreshes as needed.
The CLI fallback uses an asynchronous subprocess with upstream timeout. The
five-minute proactive timer stays dormant until Anthropic is actually used.
Account switching and upstream refresh/conflict handling remain intact.
After Anthropic use, that timer remains active even when another model is selected.
GPT-only startup, provider discovery and idle ticks never refresh Claude. Startup
still publishes the disk credential's OAuth identity into local `auth.json`,
preserving other provider entries. A terminal refresh failure does not repeat
OAuth and both CLI attempts through the request's backoff path.

Linux exposes one file-backed account slot. External account replacement is
adopted after the existing 30-second cache TTL, immediately through explicit
account authorization, or through bounded 401/429 recovery. Refresh write-back
retains upstream compare-before-write protection against an external switch.

Do not patch npm cache. Update the pinned source/hash and recheck the patch when
upgrading. Rebuild with `rehome`; restart OpenCode to load changed plugins.

## Verification

```sh
CLAUDE_AUTH_PLUGIN=/nix/store/.../opencode-claude-auth.js node --test home/features/agents/opencode/test-claude-auth.mjs
node --test home/features/agents/opencode/test-context-library.mjs
# Python needs pyyaml and plyvel; run from home/features/desktop/contexts:
python3 -B -m unittest test_context_chat_library.ScopeTests test_context_notes
PERSISTENCE_NATIVE_TESTS=1 python3 -B -m unittest test_context_chat_library.NativeLibraryTests test_native_context_sessions.NativeScopeTests
```

On 2026-10-30, PTY measurements on PC reached an input-responsive home prompt in
3.30–3.35 seconds through the context launcher, versus 3.21 seconds executing the
native binary directly with the same plugins. Neither context launch printed an
unrelated-directory warning. This compares wrapper overhead, not a plugin-free
upstream build or a cold-boot desktop restoration.

## Maintenance inventory

| Component | Source / upgrade proof |
| --- | --- |
| OpenCode | `flake.nix` tag 1.19.3, locked revision `e3c4eb242585dcd77be1a867391b7c25fd47ce52`; `package.nix` owns native patch/copy wiring |
| Claude auth | npm 2.2.1 fixed source/hash in `claude-auth.nix`; patch and 14 isolated regressions run in Nix `checkPhase` |
| Session notifications | existing `session-notify` submodule; `peripheral-plugins.nix` applies `session-notify-timeout.patch` to an immutable executable copy; no submodule revision change |
| Server plugins | auth, context library, context notebook, tmux status, notifications, existing immutable session policy |
| TUI plugins | `tui.json`; tmux theme, selection persistence and context history/stale UI |
| Supernote MCP | device-local stdio Python; initialization/listing does not contact mirror; capture is explicit |
| Skills | Caveman/TypeSafe flake inputs plus device-local skill discovery; no new services |

Pinned upstream also initializes its bundled Codex/OpenAI, Copilot, Modal,
GitLab, Poe, Cloudflare Workers/Gateway, Azure, DigitalOcean, Snowflake, xAI and
Cerebras plugins (`packages/opencode/src/plugin/index.ts:66–85`). These are native
package contents, not separately downloaded local integrations. Upstream waits
for configuration dependencies before external plugins (`index.ts:184`); a fresh
profile can therefore differ from warmed-profile timing. Acceptance must report
cold dependency initialization separately rather than treating it as wrapper cost.

tmux status/theme/persistence and notification tmux/focus helpers use 500ms
subprocess deadlines with SIGKILL, including fallback when tmux ignores SIGTERM.
Status stops spinner/retries when its server instance is disposed; theme already
disposes its polling timer. Notification origin lookup falls back to pane-only
identity rather than blocking initialization. Theme changes are deduplicated;
there is no history synchronization in that polling loop. Persistence's separate
`db path` lookup remains bounded at 10s and helper-marked; custom DB handling stays
intact. Context notebook subprocess calls are bounded at 15s.

Upgrade one pinned dependency at a time: update tag/source/hash, reapply patches,
build locally with `--builders ''`, run auth/peripheral and native integration
checks, then coordinate `rehome` and OpenCode restart. Keep helper modules outside
plugin auto-discovery (use `.mjs` or non-plugin directories). Do not patch npm cache.
`package.nix` applies patches in sessions → freshness → stale order, then copies
the shared modules and native UI helpers. Python helpers remain beside the
repository-backed launcher. Activate the matching native binary, helper links
and stale TUI entry together; restart OpenCode to load the new integration.

For an authorized integration that includes untracked source files, the explicit
path flake includes those files without staging or committing them:

```sh
rehome pc --flake path:/etc/nixos#pc --option builders '' --no-write-lock-file
```

```sh
NOTIFY_PLUGIN=/nix/store/.../session-notify.js node --test home/features/agents/opencode/test-peripheral-plugins.mjs
```

Home Manager capture units and Omega's system capture units are declaratively
omitted. `rehome` deploys Home Manager only: Omega system-unit removal additionally
needs the ordinary system rebuild. Verify both system/user unit scopes after
activation and reboot. Manual collector remains available; transcript-processing
and other note-pipeline services are separate. Whole-profile rollback must not
re-enable archived-vault capture or weaken existing desktop enforcement.
