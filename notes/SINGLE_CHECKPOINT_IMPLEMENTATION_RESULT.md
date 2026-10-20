# Single-checkpoint implementation result

## Outcome and ownership

Implemented the single-current, incremental/no-op checkpoint task. Loose/non-tmux
terminal discovery and restoration remain explicitly deferred. No commits, pushes,
commit-session launches, live-server restarts, rebuilds, or deliberate production
migrations were performed.

Both working trees were inspected before editing. Baseline snapshots/status remain
in `/tmp/opencode/single-checkpoint-20261019/`. Parent HEAD remains
`eabaf732318a3400de4864a8c52c385fdaec0337`; Neovim HEAD remains
`ea4d22f21074866c3ca0699524e98f404de63480`. Existing staged/unstaged changes and app
state were preserved. The supervisor owns independent verification and the separate
authorized commit session.

Independent gates failed and their completion markers were withdrawn. The first
repair added bounded RPC validation and fixed a process-start race, but did not
address the actual terminal-stdin-dependent RPC output routing. That cause is now
reproduced with a pseudo-terminal and fixed. Latest implementation-side checks pass
with supervisor-like PTY stdin. The subsequent independent gate passed all four
checks in `independent-checks.json`; the authorized commit-history phase inspected
that evidence and recorded its own gates in `COMMIT_HISTORY_RESULT.md`. Statements
about unchanged HEADs and no commits above describe the implementation phase.

## Format and publication

### Coordinator storage v2

`<context>/.context/state/terminal/current.json` is the only ordinary publication
root. Unowned tmux sessions use the equivalent machine-local
`desktop-contexts/terminal/unowned/terminal/` tree.

The JSON envelope contains `manifest` and its canonical-JSON SHA-256. The manifest
contains `version: 2`, content-derived publication `id`, `context_id`, `parent`,
`device`, a per-device counter `clock`, meaningful-publication timestamp/reason,
warnings, migration provenance, and `artifacts`. Each artifact has `size`, whole
`sha256`, and ordered `chunks`. Immutable `objects/<sha256>` files contain bytes.
Content-defined byte/line anchors bound chunks to 64 KiB and allow suffix reuse
after insertions. Unchanged artifact indexes are reused without rechunking.

The current index/artifacts and application captures are collected in RAM.
Application RPC occurs before publication locking; local publication uses the
existing bounded coordinator lock and rejects stale captures. The root is checked
again after object writes to catch incoming publication during a save. Changed
objects and directory entries are flushed before atomic root replacement.

`$XDG_STATE_HOME/desktop-contexts/terminal/stores/<context-id>/` holds one local
witness/index and incremental current-object mirror. One `pending.json` records the
base, intended manifest, new objects, and retired objects. This is bounded in-flight
safety data, not a generation archive. Recovery completes a published transaction's
local acknowledgement before deleting its prior witness bytes. A fork arriving
between root publication and local acknowledgement preserves the pending branch.

Routine successful saves print diagnostics without appending success logs. A normal
no-op does not create, replace, delete, or change checkpoint files/mtimes; registry
and desktop-observation writes are conditional. Raw resurrect captures are no longer
invoked or generated. Native normalized topology and deliberate program-argument
strategies continue to drive context-scoped recovery.

### Editors and chats

Neovim exposes `snapshot()` for binary-safe in-memory RPC. Base64 is only the wire
encoding; stored buffer chunks remain raw bytes. Layouts, associations, recovery
copies, explicit file/stdin startup, failure acknowledgements, and legacy sessions
remain supported. Unicode, embedded NUL, and invalid UTF-8 buffer bytes were tested.
Snapshot RPC clients and captured noninteractive commands explicitly disconnect
terminal stdin. With piped stdout and inherited TTY stdin, Neovim can otherwise
write valid RPC data to stderr and terminal control output to stdout. Intentional
`input`/`stdin` overrides on the generic command helper are preserved.
Successful CLI exit status is not accepted as proof of a valid RPC snapshot. Empty
or truncated JSON replies receive at most three RAM-only attempts sharing a total
15-second deadline. Normal capture still performs one RPC. Native failures and
schema/identity mismatches fail explicitly; persistent transport failure cannot
publish or replace the current checkpoint.

Standalone Neovim saves use one current session per directory:
`.context/state/nvim/current/<directory-key>/editor.json`, plus the existing
directory lookup namespace. Latest saving editor owns that standalone directory
session; the coordinator independently captures every editor/pane. The editor
manifest is hashed and records publication counters. Local witness/mirror and one
pending index protect changed publication. Kernel `flock(LOCK_EX | LOCK_NB)` is
nonblocking and crash-released; no PID lockfiles or callbacks into an exiting editor
are required. Editable recovery working copies are removed after successful exit
save, and preserved on failure.

Chat bundle format 2 stores session indexes, message information, individual parts,
and attachment blobs separately. Inline data URLs are also extracted into immutable
blobs and restored byte-for-byte. Native family exporters still establish portable
snapshots; read-only SQLite fingerprints and dependency hashes skip exporters on
unchanged saves. The TUI resolves its database location once at startup and exposes
that local observation over the existing authenticated socket. Process/socket
observations are excluded from logical checkpoint artifacts. Restore continues to
support format 1 and preserves deterministic imports/newer or divergent local chats;
existing native part/message IDs are not blindly overwritten.

## Migration, GC, sync and conflicts

- Latest v1 data is validated before capture and again through validated v2
  publication. Failed/incomplete migration does not remove its committed source.
- After publication, acknowledged v1 ancestors and identifiable local unpublished
  candidates are reclaimed. Other published branches are preserved under
  `legacy-conflicts/`. Unknown incoming v1 generations are retained, including
  incomplete ones, rather than swept based on an older local head.
- Structured v1 editor directory pointers remain readable. After publishing the new
  current session/pointer, the known replaced editor root can be reclaimed if no
  other directory pointer references it. Unknown incoming editor roots remain.
  Original `neovim-sessions` session-manager files are untouched.
- Raw machine-local resurrect trees are reclaimed only after validated v2
  publication. There are no new raw captures or full on-disk capture candidates.
- Object GC uses only known superseded current/witness references and locally
  journaled scratch ownership. Unknown incoming objects are never globally swept.
  Directory deletions are flushed before the transaction journal is removed.
- Referenced hashes and sizes are checked at the destination. Reordered roots,
  objects and deletions produce explicit incompleteness; no older-root fallback is
  selected. The local mirror is used for explicit conflict preservation, not silent
  recovery substitution.
- Device-counter dominance supports sequential device use. True divergence is
  preserved explicitly with its bytes, including when synced deletion arrives
  before divergence is detected. Preserved conflicts and Syncthing root conflict
  files block automatic loading/publication. Incomplete divergent pending data is
  retained and reported rather than claimed complete. No auto-merge is attempted.
- Publication scratch names are excluded from the sessions share. Successful
  restore-only adapter bundles are reclaimed after application acknowledgement;
  failed recovery remains protected.
- Existing closed/pre-kill retention, lifecycle checks, pending recovery panes and
  editor failed-startup protection remain in force.
- Shell/supported-program restoration waits for the forked tmux child to execute
  its intended process before success acknowledgement. The bounded readiness poll
  prevents temporary `pane_current_command=tmux` observations from prematurely
  clearing failed-restore retention; missing/timed-out acknowledgement is explicit.

Old and new writers should not operate concurrently against one context. A new v1
head arriving after native v2 publication requires explicit review; v1 binaries
cannot read v2. Rollback requires deliberate export/format conversion of current
data, not selection of stale historical generations. No live migration was run.

## Verification

Successful gates follow. Commands ran from `/etc/nixos` unless noted. Latest checks
use owned PTY stdin for every top-level command, matching the supervisor condition
that earlier non-TTY checks missed. They include the supervisor's exact four checks,
scoped lint and native stress cases. Unchanged configuration/compositor/
native-barrier gates from the initial implementation remain valid and were not
unnecessarily repeated during this Python-only repair.

1. **209 discovered tests: 207 passed, two intentional opt-in skips; exit 0 with
   terminal stdin.** Includes native OpenCode import/export/
   dependencies/divergence, 48 coordinator checks, ten command/RPC/process-boundary unit
   checks, 14 store checks, repository/context suites and shutdown unit checks.

   ```sh
   PERSISTENCE_NATIVE_TESTS=1 PERSISTENCE_TMUX=/nix/store/npp3sp2cbnn46bvmn1byfkb7ldlsyfsl-tmux-3.7c/bin/tmux PERSISTENCE_RESURRECT=/nix/store/fy177g0k8bk83wpzrfzpy7kz0dfgwbb2-tmuxplugin-resurrect-unstable-2022-05-01/share/tmux-plugins/resurrect /nix/store/iaadi6k26dcajhfvghqc2al1sf6v0iz4-python3-3.14.7-env/bin/python3 -B -m unittest discover -s home/features/desktop/contexts -p 'test_*.py' -q
   ```

   Skips: real graphical desktop fixture (`PERSISTENCE_DESKTOP_TESTS` remained
   unset), and explicit live system-D-Bus inhibitor probe. No native coordinator
   barrier tests were skipped with this patched binary.

2. **14 native Neovim tests passed; exit 0**, including actual 30-second timer,
   concurrent RPC/exit, no-op write-operation instrumentation, bounded edits,
   changed chunks, insertion/Unicode, binary buffers, interrupted publication,
   structured v1 migration and reordered-sync divergence preservation. The final
   invocation inherited PTY stdin; its noninteractive RPC client explicitly uses
   `DEVNULL`, preserving every original assertion.

   ```sh
   PERSISTENCE_NATIVE_TESTS=1 /nix/store/iaadi6k26dcajhfvghqc2al1sf6v0iz4-python3-3.14.7-env/bin/python3 -B home/features/development/nvim/test_persistence.py -q
   ```

3. **Native coordinator/editor scenario passed; exit 0.** The initial focused
   invocation below ran from `home/features/desktop/contexts`; the latest full and
   stress gates exercise the same assertions directly and with fault injection. Covers
   memory capture, actual filesystem no-op audit, changed-chunk isolation, exit
   while coordinator publication lock is held, real reconstruction and duplicate-
   free acknowledgement, plus restore-bundle cleanup.

   ```sh
   PERSISTENCE_NATIVE_TESTS=1 PERSISTENCE_TMUX=/nix/store/npp3sp2cbnn46bvmn1byfkb7ldlsyfsl-tmux-3.7c/bin/tmux PERSISTENCE_RESURRECT=/nix/store/fy177g0k8bk83wpzrfzpy7kz0dfgwbb2-tmuxplugin-resurrect-unstable-2022-05-01/share/tmux-plugins/resurrect python3 -B -m unittest test_persistence.PersistenceTests.test_real_editor_ram_capture_chunk_isolation_and_exit_without_publication_deadlock -v
   ```

4. **14 final store tests passed; exit 0**, including 50 no-op ticks, 150 edits,
   byte/mtime/count snapshots, inotify detection of transient writes/deletions,
   insertion suffix reuse, crash injection at each durable write/publication step,
   incoming-root races, pending-ack forks, unknown incoming preservation and v1 GC.

   ```sh
   python3 -B -m unittest discover -s home/features/desktop/contexts -p 'test_checkpoint_store.py' -v
   ```

5. **12 native tmux barrier tests passed; exit 0**, including tree-mode tagged X.

   ```sh
   PERSISTENCE_TMUX=/nix/store/npp3sp2cbnn46bvmn1byfkb7ldlsyfsl-tmux-3.7c/bin/tmux python3 -B home/features/terminal/tmux/test_checkpoint.py -v
   ```

6. **Compositor harnesses passed; exit 0** (sessions aggregate, 13 terminal tests).

   ```sh
   XDG_RUNTIME_DIR=/tmp/opencode/single-checkpoint-20261019/lua-runtime HYPRLAND_INSTANCE_SIGNATURE=test-single-checkpoint nvim --headless -u NONE -i NONE -n -l home/features/desktop/hyprland/config/sessions/test.lua
   nvim --headless -u NONE -i NONE -n -l home/features/desktop/hyprland/config/test_context_terminals.lua
   ```

7. **Picker harness passed; exit 0**, with isolated signature/runtime and no windows.

   ```sh
   QT_QPA_PLATFORM=wayland WAYLAND_DISPLAY=/run/user/1000/wayland-1 XDG_RUNTIME_DIR=/tmp/opencode/single-checkpoint-20261019/lua-runtime HYPRLAND_INSTANCE_SIGNATURE=test-single-checkpoint qs -p home/features/desktop/quickshell/test_session_picker.qml
   ```

8. **All nine Home Manager and nine NixOS configurations evaluated; exit 0.**
   Names: alpha, legion, mac, omega, pc, t470, t480s, test-vm, zombie.

   ```sh
   nix eval --json .#homeConfigurations --apply 'xs: builtins.mapAttrs (_: x: x.activationPackage.drvPath) xs'
   nix eval --json .#nixosConfigurations --apply 'xs: builtins.mapAttrs (_: x: x.config.system.build.toplevel.drvPath) xs'
   ```

9. **Scoped production/new-store lint and whitespace checks passed; exit 0.**

   ```sh
   ruff check home/features/desktop/contexts/checkpoint_store.py home/features/desktop/contexts/persistence.py home/features/desktop/contexts/chat_portability.py home/features/desktop/contexts/test_checkpoint_store.py
   git diff --check
   git diff --check --submodule=diff
   ```

   `git diff --check` also ran from
   `/etc/nixos/home/features/development/nvim/config` and passed.

10. **Historical first-repair runner: all seven checks passed; exit 0.** Its first four commands
    exactly match the supervisor's gate. It additionally runs scoped lint, a second
    full context suite, and **40 native stress cases**: 20 lost/truncated-RPC
    scenarios and 20 partial-failed-restore scenarios. Every original topology,
    recovery, chunk-isolation, no-op and exit assertion remains active.

    ```sh
    python3 -B /tmp/opencode/single-checkpoint-20261019/repair_checks.py
    ```

    This earlier run did not inherit terminal stdin and therefore missed the actual
    supervisor output-routing condition. It is historical evidence, superseded by
    the PTY verification below. Exact underlying argv, working directories, exit codes and durations are in
    `/tmp/opencode/single-checkpoint-20261019/repair-checks.json`; complete output is
    in `repair-checks.log`. Both full runs reported `Ran 205 tests` and
    `OK (skipped=2)`; the editor suite reported 14 passed; the stress suite reported
    40 passed. The runner only executes checks and records evidence; it does not
    launch either workflow or commit sessions.

11. **Latest PTY verification: all six final stages passed.** Final results are in
    `/tmp/opencode/single-checkpoint-20261019/pty-repair-checks.json`, with
    `stdin_isatty: true` for every stage. The log is `pty-repair-checks.log`.
    Stages: 209 context tests, 14 native editor tests, parent/submodule whitespace
    checks, scoped lint, and **20 native stress cases** (ten PTY capture/readiness/
    recovery scenarios and ten lost/truncated-reply scenarios). All final exit codes
    are zero; all original recovery/no-op/chunk/exit assertions remain active.

    ```sh
    python3 -B /tmp/opencode/single-checkpoint-20261019/pty_repair_checks.py
    python3 -B /tmp/opencode/single-checkpoint-20261019/pty_repair_checks.py 1
    ```

    The initial invocation exited 1 after passing the 209-test suite and exposing
    the same stdin problem in the standalone editor test harness's RPC helper.
    After that harness-only stdin fix, the resume invocation exited 0 and passed
    the remaining stages. Its argument `1` reuses only the already-passing first
    stage; it does not skip the failed editor suite. Both attempts remain in the
    log. The parent production/test sources were unchanged after that successful
    first stage, so no unrelated full-suite rerun was needed.

Development runs exposed and fixed storage-shape assumptions, RAM-root chat cleanup,
editor fixture runtime setup, binary recovery-copy writes, and publication recovery
edge cases. An exploratory lint run including all old test files also reported
pre-existing style findings; those legacy tests were not broadly reformatted.
An initial offscreen picker invocation could not load a PanelWindow backend despite
returning exit 0; it is not counted as successful evidence. The Wayland invocation
above explicitly printed its passing assertions.

### Independent-verification repair

The original independent gate stopped at
`test_real_editor_ram_capture_chunk_isolation_and_exit_without_publication_deadlock`
with `Expecting value: line 1 column 1 (char 0)`. Its original evidence remains
untouched in `independent-checks.{json,log}`. The previous completion marker was
replaced atomically with blocked status while investigating.

The editor boundary used `json.loads(run(...))`, assuming every successful native
CLI invocation carried a complete JSON response on stdout. The first repair's 240
isolated non-TTY runs did not reproduce the cause. Empty/truncated successful-reply
injection reproduced the failure path and motivated bounded validation/retries,
but a second independent run still failed. Its improved diagnostics showed valid
snapshot JSON on stderr instead of stdout: this was output routing, not random
payload truncation, and retries alone could not repair it.

**Confirmed cause:** the supervisor launches checks from a terminal. Neovim's
`--remote-expr` client, with piped stdout but inherited TTY stdin, changes output
streams and emits terminal control output. An owned-PTY reproduction returned exit
0 with 244 characters on stdout and 711,192 characters of valid snapshot JSON on
stderr, consistently across all three attempts. The same full end-to-end test
failed before the fix and passed after it; capture, readiness, exit and restored
buffer-content RPCs all retain their assertions.

`run()` now defaults captured noninteractive commands to `stdin=DEVNULL`, while
honoring explicit `stdin` or `input` callers. `editor_snapshot()` sets that mode
explicitly on every attempt. The standalone Neovim test harness's direct RPC client
needed the same setting; the PTY gate exposed and verified that correction too.
The implementation does not reinterpret stderr as a snapshot or accept terminal
escape output. Bounded validation/retries remain defensive behavior for genuinely
malformed replies. It never accepts
`null`, an old schema, a native process error, or an editor identity change as a
valid replacement. Tests verify one RPC in the normal case, the shared deadline,
bounded persistent failure, and zero transient checkpoint writes on failed capture.
Native fault injection eventually consumes a real Neovim snapshot and retains all
original end-to-end recovery assertions.

A subsequent repeated full run exposed another real race in
`test_partial_failed_restore_remains_retained_after_next_checkpoint`: a restored
shell still reported `tmux` rather than `sh`. `await_program()` previously returned
immediately for shells/supported tools, acknowledging fork before exec. It now
requires process-name acknowledgement within a bounded polling window before the
existing success/retention logic runs. Two deterministic tests failed before this
fix and passed after it; the unchanged native partial-recovery test also passed in
both earlier non-TTY full suites, all 20 first-repair stress repetitions, and the
latest PTY full suite.

Thirteen focused checks were added in `test_persistence.py` across both repairs;
none of the original behavioral assertions were removed or relaxed. The PTY repair
adds three command-stdin contract tests and one real editor PTY scenario, and
strengthens existing RPC tests to require noninteractive stdin on every attempt.
The intermediate shell-race failure is retained in
`repair-checks-attempt1.{json,log}`. `repair-checks.{json,log}` retain the earlier
passing non-TTY gate; `pty-repair-checks.{json,log}` contain the latest final
supervisor-like results, including the harness-only failure and its successful
rerun. Original independent evidence is preserved. Scope remains coordinator
capture/readiness and isolated test clients; loose terminals remain deferred and
the proven native tmux interception layer was not modified.

## Limits and deployment status

No implementation blocker remains in the requested scope. Owned ordinary state is
bounded to current objects, one mirror and one in-flight transaction. Genuine
conflicts, failed/incomplete recovery, unknown incoming objects and needed closed
contexts are deliberate retention exceptions, not periodic history. Their total
size cannot be bounded by deleting data of unknown ownership.

The protocol assumes sequential device use and Syncthing conflict delivery; it is
not a cross-device distributed lock. It validates the root again before replacement
and preserves detected forks, including transaction/acknowledgement crash races.
Application operational writes, native chat imports and editable recovery files are
separate from checkpoint no-op accounting.

No `rehome`, production rebuild, device reboot, fleet rollout or v2 real-desktop/
second-device acceptance was performed. Existing out-of-store source links may
already expose repository edits, but old editor/TUI processes still need normal
future-session activation. Historical laptop/reboot evidence in the README is v1
evidence, not a v2 rollout claim. ARM package builds and a normal-profile canary
remain deployment work. Loose terminals, native compositor tiling-tree precision,
arbitrary process memory, drafts/in-flight model work and Git snapshot objects keep
their documented limits.

## Files changed by this implementation session

Parent repository:

- `home/features/desktop/contexts/checkpoint_store.py` (new)
- `home/features/desktop/contexts/test_checkpoint_store.py` (new)
- `home/features/desktop/contexts/persistence.py`
- `home/features/desktop/contexts/chat_portability.py`
- `home/features/desktop/contexts/test_persistence.py`
- `home/features/desktop/contexts/test_chat_portability.py`
- `home/features/desktop/contexts/default.nix`
- `home/features/desktop/contexts/README.md`
- `home/features/agents/opencode/tui-plugins/context-persistence.js`
- `home/features/development/nvim/test_persistence.py`
- `system/modules/software/vault-sync/default.nix`
- `notes/SINGLE_CHECKPOINT_IMPLEMENTATION_RESULT.md` (new)

Writable Neovim submodule:

- `home/features/development/nvim/config/lua/context_persistence.lua`

## Suggested commit boundaries for the authorized session

Review the pre-existing context/repository foundation and proven native tmux barrier
separately from this storage work. Commit the Neovim submodule's prior adapter work
and incremental current-session changes coherently before recording its new parent
gitlink. Group the Python current-store/capture/chat changes with their regression
tests so imports and formats remain runnable. Keep Syncthing scratch exclusions,
runtime wrapper adjustment and format/rollout documentation with the corresponding
storage integration. Exclude unrelated application state from staged commits unless
separately intended. This session did not stage, commit, push, or launch that phase.
