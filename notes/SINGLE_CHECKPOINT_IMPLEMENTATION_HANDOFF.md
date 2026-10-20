# Handoff: single current checkpoint, incremental writes

## Latest user request and ownership

User requests a fresh OpenCode session to implement this task, then a separate
OpenCode session to assemble coherent staged commits. This is the implementation
session. **Do not commit or push.** A supervising process launches the commit
session only after implementation finishes and independent checks pass.

User has explicitly **deferred loose/non-tmux terminal support**: extra complexity
is not warranted now. Do not implement standalone-terminal discovery, Kitty remote
control, new terminal registries, arbitrary process restoration, or related launch
changes. Existing live sessions need not be backed up/migrated; prepare future
sessions. Do not restart the user's live tmux server, editors, or current chats.

Read `/etc/nixos/AGENTS.md`, applicable parent instructions, and instructions inside
the Neovim submodule. Inspect both working trees before editing. Extensive prior
context and terminal work is uncommitted; preserve it and unrelated app state.
Current baseline parent HEAD is `eabaf732318a3400de4864a8c52c385fdaec0337`; use the
supervisor's actual baseline snapshot if the branch has advanced independently.

Scope this task to storage, capture/restore adaptation, migration, tests and docs
needed for **one current checkpoint**. Preserve already-working terminal recovery.

## User's required behavior

> I just need one. When saving a checkpoint, the last checkpoint should be loaded
> into RAM. It should be modified in RAM then it should be written to disk. Only
> the bits that have actually changed should be written. If nothing changes in
> 30 seconds, nothing should be written.

Acceptance:

1. One logical current checkpoint per context, with corresponding machine-local
   fallback. No ever-growing periodic checkpoint history.
2. Load current logical snapshot/index into RAM; gather changes in RAM; write only
   changed data. Unchanged editor buffers, chats, attachments, tmux layouts and
   desktop inventory are reused, not copied for each tick.
3. A no-op save must not create/update/delete checkpoint files, stage a full disk
   snapshot, rewrite manifests/registry files, append routine success logs, create
   raw resurrect backups, or touch unchanged artifact mtimes. Ignore volatile
   capture timestamps/PIDs/socket paths when deciding logical state changed.
   Application-owned operational writes are distinct from checkpoint writes, but
   avoid needlessly invoking exporters that create logs/caches when unchanged.
4. Granularity matters: chat messages/parts and large buffer chunks should support
   changed-piece writes; a one-buffer edit must not rewrite other editors/chats or
   unchanged content of a large payload. Keep implementation proportional; do not
   build a general distributed storage platform.
5. Durable changed objects first, atomic current-manifest publication last. Keep
   only bounded in-flight safety data, not a renamed full generation archive.
   Interrupted saves must preserve a valid committed snapshot or explicitly report
   incompleteness; never silently select an older checkpoint as fallback.
6. Syncthing may deliver manifests, objects and deletions out of order. Validate
   references/hashes at destination; never garbage-collect unknown incoming objects
   just because an older local manifest does not reference them. Sequential device
   use is expected; preserve genuinely divergent data explicitly, without auto-merge.
7. Reclaim obsolete objects, unpublished scratch captures and v1 generations after
   validating migration/publication. Preserve needed closed-context/pre-kill state,
   incomplete/failed application recovery, and real conflicts. Keep old original
   Neovim session-manager sessions intact; those predate this feature.
8. Apply policy to standalone Neovim periodic/exit autosaves as well as coordinator
   saves. Do not move unbounded accumulation to another directory.
9. Collect application state outside publication locks. In particular, an editor
   exiting while submitting a save must not wait on a helper that calls back into
   the blocked editor. Bound waits; keep native tmux event loop responsive.

## Existing implementation to inspect and reuse

- `home/features/desktop/contexts/persistence.py`: current v1 generations/heads,
  artifact validation, scoped native topology, UUIDs/path relocation, retention,
  app acknowledgements, desktop restore, CLI and machine-local logs/registry.
- `.../chat_portability.py`: native OpenCode family exports, dependency blobs,
  safe import/remapping/divergence preservation. Native import ignores updates to
  existing parts/messages; do not regress this by importing blindly over local IDs.
- `.../contextctl.py`, `default.nix`, `shutdown_barrier.py`: context lifecycle,
  30-second timer, runtime dependencies, early logind delay inhibitor.
- `home/features/development/nvim/config/lua/context_persistence.lua`: writable
  Git submodule; per-editor capture, recovery buffers, directory sessions, RPC,
  readiness acknowledgements, blocked autosave after failed startup restoration.
- `home/features/agents/opencode/tui-plugins/context-persistence.js`: authoritative
  per-TUI selection over local socket. Native SQLite remains local, not synced.
- `home/features/terminal/tmux/{checkpoint.patch,package.nix,tmux.conf}`: native
  asynchronous pre-kill barrier. Avoid changing this proven interception layer
  unless storage integration actually requires it.
- `home/features/desktop/hyprland/config/context-terminals.lua`, `sessions/init.lua`,
  `workspaces.lua`, picker `state/DesktopSessions.qml`: placement/lifecycle wiring.
- `home/features/desktop/contexts/README.md`: current behavior and pending policy.
- `notes/TERMINAL_PERSISTENCE_HANDOFF.md`: original acceptance and updated decisions;
  loose-terminal work described there is now deferred by this latest request.

Current growth sources include successful coordinator generations, unsuccessful
unpublished candidates, per-editor generations, and raw resurrect `captures/UUID`
directories. Inspect all of them. Current raw resurrect capture is server-wide and
machine-local; automatic restore is context-scoped and must remain so.

A small current manifest plus immutable content-addressed objects is a reasonable
design, not a mandated API. Retain atomic publication and sync-safe completeness;
do not literally overwrite referenced artifact bytes before publishing a new root.
Avoid a new daemon unless evidence shows the existing one-shot pipeline cannot meet
requirements. Keep reusable format/GC logic at its owning layer.

## Regression contracts that must survive

- Latest-only selection; explicit missing/corrupt artifact failures; independent
  panes/windows/sessions continue; no silent older fallback.
- Close/pre-kill checkpoint before destruction; failed save leaves managed targets
  intact; periodic teardown cannot erase last closed/pre-kill recovery state.
- Multiple windows/clients, numbered/special placement, floating geometry/focus,
  duplicate-free reopening, grouped/shared windows, alternate sockets and dead
  socket recovery. Native tiling-tree precision remains an acknowledged limitation.
- Unsaved named/unnamed Neovim buffers reopen as recovery copies in saved splits/
  tabs with original association. Never implicitly overwrite project files.
- Exact per-pane OpenCode chats, native attachments/family data, deterministic
  imports that preserve newer/divergent local data. No global continue-latest.
- Failed editor/chat restoration cannot let an empty fallback overwrite recovery.
  Existing `@persistence-recovery-pending` and ready/failed acknowledgements matter.
- Explicit file/stdin editor launches remain explicit; current-directory sessions
  work; original legacy session files survive migration.

## Verification

Write meaningful tests for no-op I/O, changed-object/chunk isolation, bounded disk
growth under many edits/ticks, standalone editor saves, migration, failed saves,
publication crash points, reordered sync/deletions, conflicts, closed/pre-kill
retention and failed-restore protection. Detect writes that are later deleted too,
not merely identical final directory contents. Capture baseline bytes/mtimes/counts
and instrument write/publication operations where useful.

Existing tests to read before running/updating:

- `home/features/desktop/contexts/test_*.py`: 90 coordinator/contextctl checks plus
  prior repository/context suites. Update v1 storage-shape assumptions honestly;
  do not remove/weaken behavioral assertions to make v2 pass.
- `home/features/development/nvim/test_persistence.py`: ten native editor checks.
- `home/features/terminal/tmux/test_checkpoint.py`: twelve native barrier checks.
- `home/features/desktop/hyprland/config/sessions/test.lua`: requires isolated
  XDG_RUNTIME_DIR and a signature beginning `test-`.
- `.../config/test_context_terminals.lua`, quickshell picker harness.
- `home/features/desktop/contexts/test_desktop_persistence.py`: opt-in real desktop
  fixture; never target live user servers/windows.

Useful existing binaries for isolated tests (discover current equivalents if these
paths no longer exist):

```text
PERSISTENCE_TMUX=/nix/store/npp3sp2cbnn46bvmn1byfkb7ldlsyfsl-tmux-3.7c/bin/tmux
PERSISTENCE_RESURRECT=/nix/store/fy177g0k8bk83wpzrfzpy7kz0dfgwbb2-tmuxplugin-resurrect-unstable-2022-05-01/share/tmux-plugins/resurrect
Python with dbus-next=/nix/store/iaadi6k26dcajhfvghqc2al1sf6v0iz4-python3-3.14.7-env/bin/python3
```

Set `PERSISTENCE_NATIVE_TESTS=1` for native chat/editor checks. Keep
`PERSISTENCE_DESKTOP_TESTS` unset except deliberately running isolated desktop
acceptance. Use `/tmp/opencode` for temporary local fixtures. Use `rehome` for
deployment when needed. Do not migrate old live work or roll out the whole fleet.

Earlier real-device evidence is `/tmp/opencode/tp-a19c7/{summary,final-summary}.json`.
User permitted passwordless sudo and `t480s` reboot tests; PC must not be rebooted.
Laptop has a separate dirty checkout: preserve it. Use staged test sources rather
than overwriting `/etc/nixos` remotely. All nine home and system configurations
evaluated previously, but this does not prove new changes or an ARM package build.

## Completion protocol

1. Implement, verify, and update current docs (accurately mark loose terminals
   deferred). Leave all commits/pushes to the next session.
2. Write `notes/SINGLE_CHECKPOINT_IMPLEMENTATION_RESULT.md` with format/schema,
   migration and GC rules, exact tests run/results, known limits, deployment status,
   touched files and commit-boundary suggestions. Record real blockers honestly.
3. The initial task prompt supplies a machine-local completion JSON path. Write it
   atomically only after work/checks genuinely finish. Required shape:

   ```json
   {"status":"complete","scope":"single-checkpoint","noop_verified":true,
    "changed_piece_verified":true,"bounded_retention_verified":true,
    "no_commits":true,"report":"/etc/nixos/notes/SINGLE_CHECKPOINT_IMPLEMENTATION_RESULT.md",
    "tests":[{"command":"actual command run","exit_code":0}]}
   ```

   On a genuine blocker, use `status: "blocked"` with `reasons`; do not claim
   completion. Do not manufacture evidence or bypass failing checks.
4. Final response summarizes actual outcome. Do not launch the commit session;
   supervisor waits for this session to finish, checks the marker and runs an
   independent regression gate before opening the next OpenCode session.
