# OpenCode integration

Pinned OpenCode 2.2.6 carries context ownership/history, shared-model and
goal-aware-title patches. OpenCode 1.19.3 remains
available internally for original-database exports and rollback. The
launcher publishes local context visibility, then executes OpenCode without
checking network working directories or synchronizing chat histories.

## Startup

V2 uses `v2/config/`, `v2/state/` and `~/.local/share/opencode-v2/`; V1 settings
and its original database remain intact. The configuration/state directories are
editable repository-backed Home Manager links. Native profile overrides leave
the desktop context registry's XDG paths unchanged. Context-bound V2 requests use
standalone servers, so a shared daemon cannot mix different context environments.

The first rebuild makes a consistent SQLite backup, runs the upstream V1 history
migration, verifies identities/titles/ancestry/metadata and seeds the portable
library's new-database ledgers. `opencode-v2-handoff.service` waits for any final
V1 responses to finish, closes those V1 processes and imports their late writes
without overwriting divergent data. Pending families remain blocked until the
handoff completes. Original IDs route to verified replacement IDs. The profile
record lives in `~/.local/state/desktop-contexts/opencode-profile.json`; selecting
an older installed launcher restores the original database default on rollback.

V2 portable bundles use format 3. V2 can restore old format 1/2 bundles using the
upstream history transformer. V1 rejects format 3 before importing any members.

- `plugins/context-library.js` discovers visible portable summaries asynchronously.
  Local conversations send without freshness checks or waiting for discovery.
  Opening a portable-only
  conversation imports only its selected family. Preparation failures retain
  histories and report errors without turning missing data into readiness.
- The history picker merges local rows and portable summaries with persistent
  availability/progress/error state. Conversation-update blocking and its recovery
  overlay are removed: newer remote copies never interrupt local continuation.
  Portable import validation, ownership, and the one-time V1 profile handoff remain.
- `notebook/` resolves notebook identity from conversation ownership using local
  metadata, without probing job/repository directories.
- `tui-plugins/context-persistence.js` exposes selected-chat metadata for terminal
  recovery. Its `db path` helper explicitly skips interactive startup preparation.
- Command palette **Move session to context** offers searchable context breadcrumbs,
  including sub-contexts. After confirmation, an idle conversation and all its
  subagents transfer to the destination's portable library, preserving native
  session IDs, history and working directory. Open the destination context and
  select the chat to continue. Source history is tombstoned against resurrection;
  interrupted publication can be finished by repeating the same move. The transfer
  uses native `db` tooling and a durable device-local journal. Moving back creates
  a fresh portable identity rather than reviving a deleted archive entry.
- `tmux-theme` copies theme colors into tmux pane options; it does not restore
  windows. `tmux-status` drives work/question/completion indicators.
- `session-notify` provides desktop notifications and sounds.
- The existing evening-policy plugin remains rebuild-controlled.

Default model is `openai/gpt-6.1-sol`. No automatic model router or custom
quick/deep agents. Main-vault transcript collector remains available manually;
its user and Omega system timers are declaratively omitted while that vault is
archived. Verify activation separately on each host.

## V2 Claude authentication

`v2/claude-auth.nix` pins the V2-compatible upstream 3.0.0 plugin. Discovery checks
connection metadata without resolving or refreshing OAuth; renewal stays on the
Anthropic request path. CLI fallback remains asynchronous and bounded. Profile
preparation imports existing Claude credentials into the new method without
renewing them or deleting the old credential. Native V2 credential APIs also own
OpenAI workspace switching and renewal for the existing quota widget.

## Legacy Claude authentication

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
| OpenCode | `flake.nix` input `opencode-v2` tag 2.2.6; `v2/package.nix` owns native patch/copy/check wiring. Input `opencode` and `package.nix` retain V1 export compatibility |
| Claude auth | V2 npm 3.0.0 in `v2/claude-auth.nix` with isolated startup/expiry/switch/fallback checks; V1 npm 2.2.1 and its 14 checks remain in `claude-auth.nix` |
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
