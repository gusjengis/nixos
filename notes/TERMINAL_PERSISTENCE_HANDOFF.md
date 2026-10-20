# Handoff: Persistent Context Terminals

> Completion update (2026-10-20): single-current incremental storage and independent
> verification passed. Coherent local commits are recorded in
> `COMMIT_HISTORY_RESULT.md`. Publication and deployment remain separate; the
> Neovim submodule must be pushed before distributing its parent reference.

> Implementation update (2026-10-19): terminal coordinator, native tmux barrier,
> editor/chat adapters, desktop reconstruction, periodic saving and early shutdown
> inhibition are implemented. See
> `home/features/desktop/contexts/README.md` → **Terminal persistence** for deployed
> behavior, two successful real `t480s` reboot tests, and remaining limitations.
> Updated user decisions below supersede the original generation-retention design.

## Status and outcome

The tmux-backed terminal slice is implemented and tested, including actual
cross-device transfer and two laptop reboots for v1. Incremental single-checkpoint
storage is implemented and locally verified; it is not yet a blanket fleet release.
User has deferred
non-tmux terminal discovery/restoration to avoid extra complexity. Current behavior,
test evidence and limitations are documented in the context README.

The tree also contains earlier, unrelated context work. Inspect it before edits or
staged commits; do not overwrite, reset, or lump it into a terminal-feature commit.

### Latest decisions and next implementation work

- **Future sessions only.** Existing live work need not be backed up or migrated.
  Loading the managed packages/adapters for new sessions is sufficient; legacy
  running-process diagnostics are not a release blocker.
- **One current checkpoint.** Load the previous logical snapshot into RAM, modify
  it there, and persist only changed objects/chunks. Unchanged 30-second scans must
  write nothing to checkpoint storage, including manifests, temporary captures,
  recovery copies and routine success logs. No accumulating generation history.
- **Atomic and sync-safe replacement.** Changed objects must be durable before
  publishing the new current manifest. Keep only bounded in-flight safety data;
  validate references on receiving devices, and reclaim obsolete data without
  deleting pending incoming objects. Preserve genuine divergence separately.
- **Non-tmux completeness: deferred by latest user decision.** Do not implement
  this in the single-checkpoint rewrite. A possible later design would start
  discovery from desktop terminals, not tmux
  sessions. Track stable Kitty/terminal identities, cwd, ownership and adapter
  endpoints. Restore supported applications directly, or a reported fresh shell
  for unsupported jobs. Prove multi-window process correlation; do not guess by PID.
- **Staged commits and rollout.** A fresh implementation OpenCode session is followed
  by a separate commit-history session only after successful verification. See
  `SINGLE_CHECKPOINT_IMPLEMENTATION_HANDOFF.md` and
  `COHERENT_COMMIT_HISTORY_HANDOFF.md`. Review the existing foundation separately, publish
  Neovim submodule changes before referring parent commits, then commit/test coherent
  storage and integration changes. Finish ARM builds and a normal-profile canary
  before broader fleet rollout. No commit is implied by this documentation update.

**User outcome:** reopen a context after closing it, rebooting, or switching to
another configured device and recover its open terminal windows, their placement,
tmux arrangement, Neovim workspaces/recovery buffers, and exact OpenCode chats.
Minimize manual setup and reorientation. Build this terminal slice before other
application adapters or richer overviews.

Broader vision is in the Context Obsidian vault:
`~/sessions/Context/.context/notes/Persistent Contexts - Vision and Roadmap.md`.

## User decisions: acceptance requirements

1. **Remember every open terminal window and where it was.** Save which terminals
   were open, their tmux attachments, numbered/special workspace placement, monitor,
   tiling arrangement/order or floating position/size, fullscreen state, and focus.
   Restore multiple windows, including multiple clients of the same tmux session.
   Do not reduce this requirement to restoring one terminal scratchpad.
2. **Context-owned portable state** under `.context/state/`; machine-local fallback
   for terminal/editor sessions outside contexts.
3. **One current checkpoint; incremental updates.** Load the last checkpoint into
   RAM, update it, and write only changed pieces. If nothing changed, write nothing.
   Replace the current checkpoint atomically; do not accumulate periodic history.
   Attempt the latest completed publication. Restore
   independent items even when others fail. Log and notify failures. Never
   automatically load an older checkpoint as a fallback. Temporary transaction data
   is bounded; genuine divergence is preserved explicitly rather than silently merged.
4. **Automatic checkpointing:** periodically, before managed context closure,
   before destructive tmux commands, and during orderly reboot/shutdown. Sudden
   power loss can recover only the latest completed checkpoint.
5. **All normal tmux command entry points:** shell, tmux command prompt, session-tree
   X shortcut, keybindings, and scripts. A shell executable wrapper alone is not
   sufficient. Cover `kill-session`, `kill-server`, `kill-window`, and `kill-pane`.
6. **Editor recovery copies:** preserve unsaved buffer contents separately from
   original files. On restore, open the recovery copies in the original editor
   arrangement, retaining original-file association. Do not merely save copies
   somewhere while reopening stale originals or silently writing project files.
7. **Exact OpenCode chats per pane**, including several chats in the same directory.
   Native portable conversation snapshots, not just a rendered Markdown transcript.
8. **Sequential device use is expected.** Do not build a concurrent collaboration or
   automatic conversation-merge system for this milestone. Preserve divergent data
   if encountered instead of silently overwriting it.
9. **No duplicate restoration:** reopening an already-open saved context switches
   to it; reuse live tmux sessions and matching windows. No server-wide restore that
   unexpectedly opens unrelated contexts.
10. **Sync indicator is deferred:** user wants a launcher/picker indicator, but only
    asked to record it for later. It and uncommitted Git portability are noted in
     the Obsidian notebook; do not expand this milestone into either project.
11. **No legacy-work migration requirement.** Current running sessions may predate
    instrumentation. This work prepares future sessions; do not forcibly restart
    or migrate existing work as a prerequisite for completion.

## Original baseline (historical; inspect current code before reuse)

This section records the starting point of the original handoff, not current
implementation status. Several listed components have since been replaced or
extended; the README documents current behavior.

| Area | Files / current behavior |
| --- | --- |
| Context catalog/lifecycle | `home/features/desktop/contexts/contextctl.py`: `root`, `scan`, `catalog`, `open_context`, `terminal`, `mutation_lock`, `publish` |
| Context documentation | `home/features/desktop/contexts/README.md` |
| Hyprland runtime sessions | `home/features/desktop/hyprland/config/sessions/init.lua`: `M.close` sends normal window-close requests and waits for windows to disappear; runtime state lives under `$XDG_RUNTIME_DIR` |
| Terminal/browser/notes roles | `home/features/desktop/hyprland/config/workspaces.lua` |
| Desktop hotkeys | `home/features/desktop/hyprland/config/keybinds.lua` |
| Picker commands | `home/features/desktop/quickshell/config/state/DesktopSessions.qml`, `SessionPicker.qml`; close currently calls runtime `sessions.close` directly |
| Tmux package/config | `home/features/terminal/tmux/default.nix`, `tmux.conf`, `create_tmux_session.sh` |
| Neovim plugin to replace | `home/features/development/nvim/config/lua/plugins/project_switching.lua` |
| Obsolete project shortcut | `home/features/development/nvim/config/lua/keymaps/navigation.lua`: `<leader>sp` uses `NeovimProjectDiscover` |
| Neovim deployment | `home/features/development/nvim/default.nix`; config is a separate Git submodule, linked writable as a directory |
| OpenCode packaging/config | `home/features/agents/opencode/default.nix`, `opencode.json` |
| OpenCode integration examples | `home/features/agents/opencode/session-notify/session-notify.js`, `plugins/tmux-status.js`, `tui-plugins/` |
| Transcript archive | `home/features/agents/opencode/session-capture.py`, `session-capture.json`; sanitized/filtered Markdown capture, not portable native session backup |
| Context file sync | `system/modules/software/vault-sync/default.nix`, `home/features/desktop/contexts/repositories.py` |

At the original handoff, `contextctl terminal` launched Kitty with tmux session named
`context-<context UUID>`. Runtime-only fallback names include compositor signature
and runtime ID. Multiple terminal windows can attach to the same tmux session.
Closing Kitty generally left tmux alive. `open_context` then switched to an existing
mapped runtime or created one and showed notes; reconstruction was not yet present.

The original resurrect/continuum lines were commented out and plugin directory
was empty when inspected. Local tmux reported 3.7c. Existing project sessions also
have human-readable tmux names; do not assume all context work is already in UUID
sessions, or destructively rename/adopt ambiguous sessions.

Original Neovim used `coffebar/neovim-project` with `Shatur/neovim-session-manager` as its
dependency. Existing sessions are in `~/.local/share/nvim/neovim-sessions/`, using
absolute-directory-derived filenames. The launcher `create_tmux_session.sh` starts
`nvim .`; account for this when handling startup arguments.

OpenCode currently has local SQLite databases and WAL/SHM files under
`~/.local/share/opencode/`. This directory also contains credentials and caches;
do not relocate/synchronize the whole directory as the portability mechanism.

## Architecture reference (new single-checkpoint policy takes precedence)

Use tmux-resurrect as a capture/reconstruction foundation, plus a context-aware
coordinator and editor/chat adapters. Verify the pinned plugin's actual behavior
rather than assuming per-session operations: stock resurrect is server-wide.

Original suggested ownership layout (not the current v1 directory schema):

```text
<context>/.context/state/
  terminal/                 # desktop terminal inventory and generation manifests
  tmux/                     # context-scoped resurrect data
  nvim/                     # editor sessions and unsaved-buffer recovery copies
  opencode/                 # native conversation snapshots and identity mappings
```

The current checkpoint needs a schema version, context UUID, publication identity/time,
source device, stable terminal/tmux/editor identities, relative artifact references,
and enough integrity information to detect missing or incomplete data. Publish a
replacement only after its changed artifacts are complete. An atomic manifest rename is
useful locally, but **Syncthing can deliver files out of order**: destination must
validate referenced artifacts before using the checkpoint. Never silently substitute
an older generation when the selected latest checkpoint is incomplete; wait/report.

Reuse immutable content-addressed pieces; this is not permission to retain periodic
checkpoint history. Keep latest closed-session
checkpoint available: later periodic scans of a server without that session must
not replace it with an empty checkpoint. Define lifecycle explicitly so deliberate
pane edits are captured but teardown after pre-close save does not erase restore
state. A pre-kill checkpoint must include the things being removed.

Keep process IDs, tmux pane IDs, Hyprland window addresses/runtime session IDs, and
monitor names as local observations, not durable identities. Store stable logical
IDs and construct fresh ID mappings on restore. Paths inside the context should be
context-relative; map external working roots explicitly. Handle whitespace and
different home/context root paths across devices.

Outside a context, keep backups in an XDG machine-local state directory. Determine
ownership from explicit saved associations and registered context metadata rather
than guessing from current active desktop alone. A context's pane can `cd` outside
its directory and still belong to that context.

## Workstream A: desktop terminal windows

- Track every context-owned terminal, not only `special:session-...-terminal`.
  Include numbered workspaces, nonfocused workspaces, and multiple terminal clients.
- Capture the terminal-to-tmux attachment relationship independently of tmux's
  internal pane tree. Tmux alone cannot restore Kitty window geometry or desktop
  placement. Define handling for terminals without a tmux attachment; migrate/wrap
  launch paths where appropriate, and report unsupported process restoration.
- Capture logical workspace slot/role and monitor placement, floating geometry,
  tiling order/tree where compositor APIs support it, fullscreen/zoom semantics,
  active workspace, visible special workspace, and focused terminal.
- Resolve missing/different monitors with deterministic, on-screen placement and
  report approximations. Do not replay raw pixels onto an unavailable output.
- On reopen, reuse live backing sessions, reconstruct missing ones, create only
  missing terminal clients, place windows after they map, restore focus last.
- Distinguish initial automatic restoration from explicit user requests for another
  terminal window. Idempotence must not disable the latter.
- Capture inventory before context/window destruction and before compositor exit
  on reboot. Periodic capture is the fallback for unexpected terminal closure.

## Workstream B: tmux checkpointing and pre-destruction interception

Package resurrect with Nix. Evaluate continuum versus a dedicated checkpoint
timer; continuum normally depends on status-line updates, and this config permits
hiding the status bar. Automatic saving must not depend on a visible status line.

Extract or generate context-scoped capture/restore data without restoring the entire
tmux server. Preserve layout, window/pane order and names, working directories,
selection, and supported program reconstruction. Test linked/grouped windows and
multiple clients, or report unsupported cases explicitly. Do not blindly replay
every recorded shell command; provide deliberate restoration strategies for Neovim
and OpenCode rather than claiming arbitrary live-process recovery.

Explicitly add `btop` to tmux-resurrect's program restore list. Restart it in its
saved pane and working directory; no custom internal-state adapter is required.
Verify it returns during restoration. Keep the default supported programs, and add
other terminal tools later as the user identifies missing programs they care about.

**Pre-kill coverage is a hard requirement.** Stock tmux's after/closed notifications
are too late, and command aliases do not override existing built-in command names.
Investigate a small Nix-managed server-level patch or an equivalently proven native
interception point. A patch is proposed, not yet designed or tested.

Required behavior:

1. Resolve actual affected sessions/windows/panes, including `kill-session -a`,
   group/target flags supported by the installed version, and alternate sockets.
2. Pause the destructive command queue while checkpointing, keeping the server
   event loop responsive. External resurrect scripts query the server: blocking
   the event loop while waiting for those scripts would deadlock.
3. Flush editor/chat state, capture affected data and terminal inventory, validate
   and publish checkpoint, then continue the original command exactly once.
4. On failure, leave targets intact and surface the error. Handle helper timeouts,
   target disappearance, recursion/reentrancy, and correct queued-command ordering.
5. Ensure shell, command prompt, tree-mode X, keybindings, and scripts hit the same
   coverage. Tree mode may use a different internal deletion path; inspect it.
6. Ship the same package to all relevant launchers/runtime dependencies. Existing
   servers keep running their old binary until restarted; installing a patched
   client does not upgrade an already-running server.

Managed context close also needs a synchronous checkpoint barrier before sending
window-close requests. Current picker routes directly to `sessions.close`; cover
all context-close paths without stuffing personal checkpoint policy into the
reusable compositor session engine unnecessarily.

## Workstream C: Neovim

- Replace neovim-project with direct session-manager configuration; remove its
  directory allowlist and project-discovery shortcut. Preserve existing sessions
  and unrelated Neovim behavior/dependencies.
- Walk upward from launch cwd to nearest `.context/context.json`; context launch
  metadata may also be needed when cwd is outside the context. Use context storage
  when owned, existing local storage otherwise.
- Restore current-directory session, never unrelated last-project fallback.
  `nvim .` should get directory-session behavior; explicit file arguments and stdin
  must remain explicit and must not be replaced by old workspace state.
- Handle context/directory changes within a running editor deliberately. Do not
  leave a startup-only sessions_dir pointing at the wrong context after switching.
- Give multiple editors in one directory distinct stable identities for tmux
  reconstruction; normal directory sessions alone overwrite one another.
- Remove machine-specific absolute-path dependence from both session keys and
  contents. Migrate old directory-keyed sessions without deleting originals first.
- Save periodically, on exit, and on coordinator request before destruction. An
  acknowledged checkpoint should describe the actual current buffer/split state.
- Preserve unsaved named/unnamed buffers as recovery artifacts with original path,
  filetype, encoding/newline metadata as needed, and editor/window association.
  Reopen recovery artifacts in their original split/tab positions. Show original
  path association; never overwrite original file as an implicit restore step.
  Unmodified buffers reopen their original files normally.

## Workstream D: OpenCode

The agreed alternative to syncing live SQLite is automatic **native conversation
export/import**, with local databases remaining local working storage.

- Track exact active conversation for each logical pane, including chat switches
  with no new message, multiple UIs in the same directory, and empty/new chats.
- Existing notification plugin demonstrates tmux-origin capture, but server bus
  activity alone does not prove which chat a particular TUI is displaying. Verify
  TUI-side selection hooks and distinguish parent chats from subagent sessions.
- Export versioned, complete conversation data automatically into the context and
  before managed close; preserve pane-to-chat and working-directory mappings.
- On restore, reconcile/import into local database and resume exact corresponding
  chat. Do not use global/directory “continue latest” heuristics.
- Probe installed version's export/import first: messages, tool parts, compaction
  records, referenced attachments, child-session relationships, project association,
  session identity preservation/remapping, and repeated import/update behavior.
  If native export omits required data, report the gap and extend capture narrowly;
  do not call rendered transcript capture equivalent.
- Preserve newer local data or divergent device generations rather than blindly
  importing over them. Initial product assumes sequential device use, not merging.
- Provider authentication remains machine-local. Account for model/agent availability
  and directory differences. Investigate unsubmitted prompt recovery if exposed;
  do not promise it without proof.
- Existing transcript capture reads known global DB paths; assess impact of new
  imported conversations without replacing its archival purpose.

Documented commands, to validate against installed version:
`opencode export <id>`, `opencode import <file>`, `opencode --session <id>`.
An imported session may need an ID mapping; do not assume identical IDs without a
round-trip test. In-flight tool/model operations do not resume mid-execution.

## Workstream E: lifecycle, reporting, deployment

- Use a coordinator to capture editor/chat state, tmux state, and desktop terminal
  inventory into a coherent generation. Serialize overlapping saves without holding
  locks that prevent queried applications from responding.
- Use periodic saving independent of visible UI. Add orderly shutdown/reboot saving
  with verified systemd ordering: run while user services, tmux, editors, OpenCode,
  and compositor APIs remain available. A late shutdown hook after compositor exit
  is insufficient. Bound waits and report failed checkpoints.
- Syncthing transport completion is separate from local checkpoint completion.
  Do not claim remote readiness solely because local save succeeded. Implement
  destination completeness checks now; leave picker indicator UI for later.
- Best-effort restore the latest selected completed generation, log individual
  errors, notify a concise failure summary, and continue unaffected items. No
  automatic older-generation fallback. Keep machine-local runtime logs separate
  from portable state where practical.
- Keep editable configuration beside its owning Nix module and deploy writable
  configuration using Home Manager out-of-store links. Neovim config is a Git
  submodule; inspect its own status before changes. Do not commit unless requested.
- Use `rehome` for deployment if available, per repository instructions. Validate
  package wiring and avoid destructive tests against the user's live tmux server.

## Original implementation sequence (historical)

The feasibility gates and end-to-end tmux-backed recovery tests below have been
completed. Use the latest decisions at the top for remaining implementation work.

1. **Feasibility gates:** prove resurrect capture/restore on isolated socket,
   OpenCode native round-trip, Neovim storage/argument handling, and pre-kill server
   interception without event-loop deadlock. Report concrete blockers early.
2. **Stable identities and checkpoints:** context ownership, portable paths, artifact
   completeness, local fallback, retained pre-close generation.
3. **Editor/chat adapters:** migrate existing sessions, prove multiple instances and
   unsaved-buffer recovery, then attach adapters to tmux reconstruction.
4. **Terminal window restoration:** inventory, placement, multiple clients, focus,
   idempotent open and integration with managed context close.
5. **Destruction/shutdown coverage:** all requested native tmux entry points,
   independent periodic saving, correctly ordered reboot checkpoint.
6. **End-to-end proof:** real reboot and second configured device after isolated
   tests pass. Explain any unverified behavior rather than marking it complete.

## Acceptance tests

Create a disposable context containing two or more Kitty windows on different
numbered/special workspaces, a floating terminal, multiple clients of one tmux
session, multiple tmux windows/panes, two Neovim instances sharing a directory,
modified and unnamed buffers, and two distinct OpenCode chats in that directory.

- Close/reopen context: correct window count, attachments, placement, layout, focus,
  editors/recovery copies, and chats. Reopening again adds no duplicates.
- Close only terminal client: live tmux remains and reattaches without losing state.
- From shell, command prompt, tree X, and bindings: delete sessions/windows/panes;
  verify checkpoint exists **before** deletion and can reconstruct removed items.
- `kill-server` on an isolated socket captures every owned session; killing one
  target does not unexpectedly affect unrelated sessions/servers. Exercise command
  chains, targets, multiple clients, failure, timeout, and helper-query responsiveness.
- Save failure prevents managed destruction. Later periodic saves do not erase the
  last closed-session checkpoint. Unsupported item failures do not block unrelated
  restoration or trigger an older-generation fallback.
- Neovim: unlisted directory autosaves/restores; explicit file/stdin behavior stays
  correct; old sessions survive migration; recovery copies reopen with original
  association and original project files stay unchanged.
- OpenCode: exact per-pane chats after switches; native export/import round-trip;
  repeated import creates no unwanted duplicates and does not overwrite newer data.
- Orderly reboot saves while applications/compositor are alive, then restores after
  reboot. Crash simulation restores latest completed checkpoint, not nonexistent
  in-memory changes.
- Second device: changed home/root path and monitor topology; complete sync required;
  missing/corrupt artifact produces explicit report, no silent old-state fallback.
- Outside-context tmux/editor sessions use local fallback and remain functional.
- Real second-device and reboot tests must be distinguished from simulations.

Existing relevant test suites include context tests under
`home/features/desktop/contexts/test_*.py` and compositor session tests in
`home/features/desktop/hyprland/config/sessions/test.lua`. Read their harness before
running; add focused tests for new behavior. No runtime tests are needed merely to
edit this handoff.

## Boundaries and deferred work

- No full process-memory checkpointing, automatic replay of arbitrary shell work,
  or mid-execution continuation of builds/model requests/tools.
- Git checkout contents are excluded from context Syncthing. Modified/untracked
  working-tree transfer is explicitly deferred, already noted in Obsidian. Tests on
  another device need matching working files supplied separately. Recovery copies
  protect edited buffers; they are not a complete working-tree transport solution.
- Browser/app restoration, workspace icons, graphical previews, saved-context
  thumbnails, and sync-status UI belong to the broader roadmap, not this milestone.
- If terminal dimensions/output availability differ, preserve logical arrangement
  as closely as possible and report limitations; do not promise identical pixels.
- Implementation and actual test evidence are recorded in the README and
  `SINGLE_CHECKPOINT_IMPLEMENTATION_RESULT.md`. Incremental single-checkpoint
  storage is complete; non-tmux completeness remains explicitly deferred. Historical
  v1 device/reboot evidence does not establish a v2 fleet rollout.
