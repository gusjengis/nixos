# Persistent Desktop Contexts

Personal persistence layer above the reusable Hyprland `sessions` module. The
runtime module owns live workspaces/windows and exposes remembered logical views.
Notebook, synchronization, checkpoint and startup policy live in the personal
context layer rather than the reusable backend.

## Use

- `Super+Z`: switch between open runtime sessions only. Enter switches; unmatched
  searches never create sessions.
- `Super+Shift+Z`: saved-context dispensary. Enter opens/restores a saved context;
  already-running contexts are marked and reused rather than duplicated.
- In the dispensary, type `Research/New idea`, then `Ctrl+N`: create a nested
  persistent context. Enter also creates when there are no matching contexts.
- `Super+N`: context notebook. First open automatically shows it.
- `Super+T`: context terminal scratchpad; tmux starts in its working directory.
- `Super+Q`: another terminal attached to that context's tmux session.
- `Super+F`: file manager at the context working directory.
- `Ctrl+D` in runtime switcher: close running session, never delete saved context/notes.
- F2 in runtime switcher: rename runtime session only, not its saved directory.
- F2 in dispensary: rename a closed non-repository context (close descendants/windows first).
  Repository contexts cannot yet be renamed: Git-sync paths and compatibility
  symlinks would also need updating.

Contexts are directories under `~/sessions`, identified by `.context/context.json`.
Nested contexts use nested directories; a parent need not itself be a context.
Each has `.context/notes`, an independent Obsidian vault, with `Home.md` as its
starting point. Obsidian saves edits automatically. There is no desktop Save step.
Home is a starter note, not a required system file; it can be renamed or removed.

Git checkouts are embedded as `<context>/<repository>`, beside `.context`.
The context's `working_directory` is a contained relative path, normally `.` or
the primary checkout's directory name. There is no reserved `work` directory.
Notes/config stay outside the checkout and therefore outside its Git history.
Missing checkouts fall back to the context directory; the notebook still opens.
All other ordinary files and folders beside checkouts are free-form synced work.

## Synchronization

The NixOS `vaultSync` module adds a separate `sessions` Syncthing share, with the
same peers as existing Obsidian synchronization. Ordinary context documents,
metadata and vaults sync. Explicitly registered checkout directories, `.git`,
Obsidian workspace files, and caches do not. Repository content remains Git-managed.
Even an ordinary folder named `work` syncs; it has no special meaning. Per-context Obsidian
Electron profiles, tmux processes and compositor mappings remain local under
`~/.local/state/desktop-contexts`.

The share requires deployment on both peers. New desktop contexts then need no
per-context share setup. Syncthing conflicts are not automatically resolved.
Avoid editing the same note concurrently on disconnected machines. Omega's
incoming version retention is not an independent backup.

## Git Repositories

Normal Git commands are wrapped by the Home Manager Git package. For example:

```sh
cd ~/sessions/Resume
git clone https://github.com/gusjengis/Resume.git
```

Before invoking real Git, the wrapper finds the owning context, records the
checkout destination in `repositories` inside `.context/context.json`, generates
an exact root-relative Syncthing exclusion, and confirms the live exclusion with
Syncthing. If that protection cannot be confirmed, cloning does not start.
No manual JSON editing is required. Outside contexts, Git operates normally.

The system `session-repository-sync.service` updates exclusions when synced
context metadata changes. It runs independently of the compositor on all vault
sync hosts. A pre-start generator establishes exclusions before Syncthing starts.
Generated `.context-repositories.stignore` and `.context-repositories.json` files
are local, excluded state. Historical checkout exclusions remain conservative;
removing a registration does not silently start syncing its old files.

The wrapper also protects `git init` in new/empty directories. It rejects context
roots, ambiguous/unsupported protected clone syntax, separate Git directories,
and nonempty unregistered init destinations rather than risk syncing a checkout.
Clone failures retain the registration and exclusion for partial data.

This is not universal filesystem interception: absolute Git paths, Git libraries,
Git aliases, development shells supplying another Git, direct directory moves,
and `git worktree add` can bypass the wrapper. Do not use those to create or move
unregistered repositories into the synced tree. Existing-file adoption needs
deliberate registration; it cannot retract files already synchronized.

## Implementation

`contextctl watch` observes the backend's atomically published JSON snapshot,
records active context changes locally, and publishes a separate picker catalog.
No personal policy or hooks execute inside the reusable session backend.
`session-env-sync` starts the watcher with the current compositor environment.

`contextctl create NAME [--open]`, `list`, `open UUID`, `rename UUID NEW_LEAF`,
`notes`, `terminal`, and `files` are available independently of the picker.
Launch commands can receive `--runtime ID` to bind delayed scratchpad launches
to their originating session rather than whichever context is now active.

Each notebook uses a local, UUID-keyed Electron profile. Window ownership follows
the process profile (native Wayland ignores the requested custom class), not
ambiguous titles. A native workspace opens Home on first use; subsequent opens
preserve Obsidian's saved workspace. No startup URI is needed, avoiding a vault
loading race observed during testing. Existing global Obsidian settings stay
untouched. Profiles are not synced. Extra processes use more memory than multiple
vault windows sharing one process.

`migrate-repos.py` defaults to a dry run. `--apply` relocates ordinary clones from
`~/Documents/Code`, preserving dirty/untracked files and old paths as compatibility
symlinks. Linked worktrees are skipped. The local migration journal records all
moves. It never commits, pushes, cleans, or replaces an existing destination.
Destinations are registered and live exclusions confirmed before relocation.

`flatten-repos.py` migrated the earlier `<context>/work/<repository>` layout.
It has separate dry-run, `--prepare` (register both paths), and `--apply` stages.
Session sharing must be paused on participating hosts while preparing; establish
exclusions on every peer before applying. Only empty old `work` directories are
removed. The flatten journal retains recovery steps; existing documents inside
`work` are preserved and now sync normally. Old `Documents/Code` compatibility
symlinks are updated to flat destinations; no replacement `work` symlink is made.

## Boundaries

- Saved context means notebook/configuration/directory, not restored app memory.
- Terminal window placement, tmux/editor reconstruction and exact OpenCode chat
  restoration are implemented; see the terminal persistence section below for
  tested behavior and remaining gaps. Browser/other graphical-app restoration and
  automatic opening of all contexts after login are deferred. Open a saved context
  through the picker to restore its supported terminals.
- Runtime-only sessions remain usable; they have no persistent notebook yet.
- Focus restrictions, lifecycle scripts, wallpapers and Supernote switching are
  deferred. Synced scripts are never executed automatically.
- Context inheritance is organizational only; no parent hooks or apps are run.
- Config files must finish syncing before discovery; incomplete/duplicate-ID
  contexts are reported by the watcher, not silently overwritten.

## Tests

```sh
python3 -B -m unittest discover -s home/features/desktop/contexts -p 'test_*.py'
```

## Terminal persistence

Terminal recovery is implemented by `persistence.py`, the native tmux checkpoint
barrier, Neovim's `context_persistence` module, and OpenCode's TUI selection/native
snapshot adapter. Existing context catalog and repository-management behavior is
preserved.

### Storage and selection

Storage v2 keeps **one logical current checkpoint per context**, plus a bounded
machine-local mirror of that current state. It does not create periodic history.

- Portable root: `<context>/.context/state/terminal/current.json`. Its envelope
  hashes a version-2 manifest containing context identity, publication ID, parent,
  device counters, warnings, and an artifact index. Each artifact records byte
  length, SHA-256 and ordered chunk hashes. `objects/<sha256>` holds immutable bytes.
- A save loads the current index/artifacts into RAM and gathers editor/chat/tmux/
  desktop state there. Capture timestamps, process IDs, RPC socket paths and native
  layout checksums do not determine logical changes. Only changed objects and the
  small root/index are written. Content-defined chunks (at most 64 KiB) resynchronize
  after insertions; chat messages, parts and external/inline attachments have
  independent artifact boundaries.
- An unchanged 30-second scan performs **zero checkpoint writes**, including
  temporary create/delete operations, registry rewrites and routine success logs.
  Neovim RPC returns memory snapshots with binary-safe base64 wire payloads (stored
  chunks remain raw bytes). Read-only SQLite fingerprints and dependency
  hashes let unchanged chats skip native exporters. Native SQLite stays local.
- Editor capture validates successful CLI replies rather than treating exit status
  as proof of a complete snapshot. Noninteractive commands and snapshot RPC clients
  disconnect inherited terminal stdin: otherwise Neovim can put its response on
  stderr and terminal control output on stdout. Empty/truncated JSON replies get
  at most three RAM-only attempts within one 15-second deadline; normal capture
  uses one RPC.
  Persistent malformed replies, native errors and schema/identity mismatches retain
  the previous checkpoint and cancel managed destruction.
- New chunks are flushed before atomic root replacement. A machine-local pending
  journal lists owned new/retired objects; recovery either keeps the valid committed
  root or reports missing/corrupt data explicitly. There is no older-root selection.
  Independent recoverable panes/windows/sessions still continue.
- `$XDG_STATE_HOME/desktop-contexts/terminal/stores/<context-id>/` holds one local
  witness/index, its incrementally updated object mirror, and at most one pending
  transaction. The mirror protects local divergent bytes against synced deletions;
  it is never silently substituted for incomplete synced state. Unowned tmux
  sessions use `terminal/unowned/terminal/` with the same current-root policy.
- GC deletes only known superseded objects from an acknowledged current/witness or
  a local pending transaction, after publication validation. Unknown incoming
  objects are not swept based on an older root. Out-of-order sync/deletions can
  temporarily make the current root incomplete; validation fails until delivery
  completes. Publication scratch is excluded from the sessions share.
- Device counters accept sequential device use. A replaced root that does not
  dominate the local witness is preserved under `conflicts/<publication-id>.json`,
  with its bytes recovered from the local mirror if necessary; saving stops for
  explicit conflict resolution. Syncthing `current.sync-conflict*.json` files and
  preserved conflicts block automatic loading/publication. There is no automatic
  merge or choice between divergent roots.
- Restore-only adapter files are materialized locally, never as a capture stage.
  Successful application acknowledgement removes these temporary bundles. Failed
  application recovery remains protected and visible.

#### Migration and standalone editors

The latest v1 generation remains readable until a validated v2 root is published.
Migration then reclaims its acknowledged ancestors and identifiable local
unpublished candidates. Other published branches are preserved under
`legacy-conflicts/`; unknown incoming v1 generations remain untouched until their
ownership/references can be established. A newly arriving v1 head after native v2
publication requires explicit review. Do not run old and new writers concurrently
against the same context; v1 binaries cannot read v2. Rollback requires an explicit
format conversion/export, not silently selecting an older generation.

Standalone Neovim periodic/exit saves use one current directory session at
`.context/state/nvim/current/<directory-key>/editor.json` (or its XDG fallback).
The last saving editor owns that directory session, as with the earlier latest
directory pointer; coordinator checkpoints still capture every editor independently.
Neovim uses immutable content-defined buffer chunks, a hashed atomic manifest,
device counters, local witness/chunk mirror and bounded transaction journal.
Unchanged saves write nothing. A nonblocking local publication lock protects
changed saves; capture happens first and helpers never call back into a blocked
exiting editor. Incomplete/conflicted state blocks replacement. Known superseded
structured v1 editor roots are removed after directory-pointer migration; roots
still referenced by other directories and unknown incoming roots remain intact.
Original `neovim-sessions` session-manager files are never removed or overwritten.
Editable recovery copies are application working files and are reclaimed after a
successful exit save; failed saves preserve them.

Context/home paths are relocated on restore. External working roots require explicit
machine-local mappings in `terminal/external-roots.json`, for example
`{"/old/external/root": "/new/external/root"}`. Longest matching root wins.
Source process IDs, compositor addresses, and tmux IDs are observations; stable
UUIDs and fresh local mappings own reconstruction. Alternate tmux servers retain
logical server identities and receive separate local sockets.

### Lifecycle

`context-checkpoint.timer` attempts a save every 30 seconds independently of tmux's
status bar. Unchanged attempts are no-ops. `contextctl close --runtime ID`
checkpoints synchronously before any compositor
close request. Picker and normal `sessions.close` calls use this barrier. Closed
contexts retain their checkpoint until reopened. Pre-kill and partially failed
restores retain missing objects so later periodic scans cannot erase recovery data.
If retained removed panes coexist with newly added panes, a coherent stacked
recovery arrangement is published with an explicit approximation warning.
Restoration waits for new shells/supported programs to execute before acknowledging
success and clearing failed-restore retention. A forked tmux child is not yet proof
that the requested process started. Missing/failed process acknowledgement remains
an explicit, retained recovery failure.

The Nix tmux overlay intercepts native `kill-session`, `kill-server`, `kill-window`,
and `kill-pane`, including aliases, scripts, prompts, keybindings, and tree-mode
tagged `X`. The originating queue waits while the event loop answers helper
queries. Actual flags/targets select affected contexts, including linked windows.
Failure, timeout, concurrent/recursive destruction, replacement targets, and a
changed server topology cancel destruction. The helper has a 90-second limit.
Native tmux records provide topology directly; raw server-wide resurrect captures
are no longer created. Existing raw captures are reclaimed after validated v2
publication. Supported program arguments are captured deliberately; `btop` is added.
Other arbitrary shell jobs are reopened as shells with a warning.

Orderly shutdown uses an already-held logind **delay inhibitor**. It checkpoints
during `PrepareForShutdown`, before graphical/user-session teardown, then releases
the inhibitor. System configuration provides a 120-second delay ceiling; helper
work is bounded to 90 seconds. A late user-service `ExecStop` is not used as proof
that compositor APIs are still alive. Failures are logged/notified and cannot hold
shutdown indefinitely. Compositor-exit and power hotkeys also checkpoint first.

### Editors and chats

Neovim uses direct session-manager configuration for exact-directory legacy
migration plus structured, portable per-instance recovery. `nvim .` restores its
directory session; explicit file/stdin arguments remain explicit. Entering another
context deliberately updates ownership; leaving a context directory retains that
association. Named/unnamed modified buffers reopen as editable recovery copies in
their saved splits/tabs, with `b:context_original_file` / `b:context_original_path`.
Implicit restore and ordinary `:write` on a recovery buffer do not overwrite the
original project file or published artifact.

OpenCode's TUI plugin reports the actual displayed route over a local socket,
including selection changes without messages and empty home/new-chat views. Native
exports capture the selected chat's family and referenced attachment/tool-output
blobs. Restore preserves exact IDs when equivalent; changed/divergent local chats
are preserved and a separate deterministic native snapshot version is imported.
Repeated restore is idempotent. Provider authentication remains machine-local.
The sanitized Markdown transcript archive continues its separate archival role.

### Operations and activation

```sh
context-checkpoint doctor
context-checkpoint save --context CONTEXT_UUID
context-checkpoint verify --context CONTEXT_UUID
context-checkpoint restore --context CONTEXT_UUID --no-windows
contextctl open CONTEXT_UUID
```

`verify` establishes artifact completeness **on the device where it runs**, not
Syncthing transport completion on another device. Picker sync-status UI remains
deferred. Desktop window restoration normally runs through `contextctl open`;
explicit `contextctl terminal` still creates another client intentionally.

Deploy with `rehome`; deploy the system configuration for logind's delay setting.
Reload logind after the system switch if its live `InhibitDelayMaxUSec` is still
five seconds. `context-shutdown-barrier.service` starts after graphical environment
import; headless hosts start it from the user default target.

**Installing a patched tmux client does not upgrade an existing server.** Run
`doctor`; save live work before restarting old servers. Existing Neovim/OpenCode
processes also need the new adapters loaded. Quit/restart OpenCode to activate its
TUI plugin. Failed adapter capture blocks managed destruction rather than claiming
an exact checkpoint. The implementation does not forcibly restart live work.

Scope is **future sessions**. Backing up or migrating work that predates these
adapters is not a user requirement or a fleet-release gate. Fresh sessions must
use the configured package/adapters. Diagnostics about old running processes remain
useful activation information, not unfinished legacy-migration work.

### Non-tmux terminals: deferred

Managed context terminal launchers already start tmux. For a plain Kitty terminal,
the current implementation does not fully reconstruct its process; a context with
only unattached terminals can also be missed because capture discovery starts from
tmux sessions. This remains a documented gap. User explicitly deferred this work:
the extra complexity is not warranted now, and it is not a requirement for the
single-checkpoint rewrite or its commit-history phase.

If revisited later, desktop terminal inventory would become independent of tmux:

1. Discover every context-owned terminal, including contexts with zero tmux
   sessions. Retain explicit ownership when its shell changes directory.
2. Assign a stable terminal identity at future launch, then associate compositor
   window, Kitty OS window/tab/pane and foreground process. Use Kitty metadata and
   supported local IPC where needed; do not equate one Kitty PID with one window.
   Prove multi-OS-window correlation before claiming it supported.
3. Register Neovim/OpenCode adapter endpoints against terminal identities even when
   `TMUX`/`TMUX_PANE` are absent. Process IDs and start times validate live endpoints;
   they are not portable restore identities.
4. Restore an unattached terminal as an unattached Kitty window at its saved
   placement/cwd, with its supported editor/chat/tool where identifiable. An idle
   shell reopens at its cwd. Unsupported jobs get a clearly reported fresh-shell
   fallback; arbitrary commands are not blindly replayed.
5. Reuse matching live windows, and keep failed application recovery references
   rather than replacing them with an empty fallback workspace.

This does not require moving existing terminals into tmux. It uses the same
checkpoint, editor/chat adapters and placement code, with a different terminal
attachment descriptor.

### Verification and remaining limitations

Automated tests live in `test_persistence.py`, `test_chat_portability.py`,
`test_shutdown_barrier.py`, `test_desktop_persistence.py`,
`../hyprland/config/test_context_terminals.lua`, `../../terminal/tmux/test_checkpoint.py`,
and `../../development/nvim/test_persistence.py`.

The original v1 implementation was verified on this machine with 42 coordinator/native integration tests, 12 native tmux
barrier tests (including actual tree `X`), ten isolated Neovim tests, native
OpenCode family/attachment/import-divergence tests, seven shutdown tests and a real
inhibitor acquisition, plus a real disposable desktop close/server-destruction/
reconstruct/reopen test with three Kitty windows, two editors and two exact chats.
The desktop test checks numbered/special placement, floating geometry/focus,
multiple clients, recovery buffers, and duplicate-free reopening. Cross-root editor
and chat portability has been simulated. Existing context and compositor-session
suites also pass.

Historical v1 second-device/reboot acceptance also passed on `t480s` on 2026-10-19:

- Existing Syncthing sessions transport delivered the disposable completed context;
  destination artifact validation passed before use. Missing/corrupt-artifact
  rejection was checked with an older generation present.
- Source context parent was `/tmp/opencode/desktop-persistence-to1_90i5/contexts`;
  destination was `~/.local/state/terminal-persistence-acceptance-a19c7/relocated-contexts`.
  HOME changed from that source fixture's `home/` to destination `fake-home/`.
  Source `HDMI-A-1` placements recovered on laptop `eDP-1` with reported fallback.
- Three Kitty windows/clients, two editor identities in the same directory, six
  modified buffers (context-file, unnamed, HOME-file per editor), and two exact
  native TUI chats recovered. Repeated restore preserved processes/window count.
- Unsaved `before-reboot-a19c7-{1,2}` markers were added without a manual checkpoint
  and were absent from the preceding generation. Actual logind shutdown capture
  completed in 12.26 seconds while compositor/editor/chat APIs remained available.
- First boot changed from `783f2b76-7e05-4652-88c7-28ac8a9aadc3` to
  `86f8e5e9-9053-4442-8c72-2f704737b657`. Automatic test reopening recovered latest
  `reason=shutdown` generation
  `generations/1792428318964446936-t480s-bbd74482-8fbe-4bfb-8fd3-2e20bbc1c0f5`,
  including all six marker-bearing buffers, both chats and three windows/clients.
- Final application-acknowledgement build passed a second real reboot to
  `5897cf25-de26-4f59-99f0-3ac19cee8fd9`. Unsaved
  `final-code-reboot-a19c7-{1,2}` markers survived in all six buffers through
  `generations/1792429315777200234-t480s-93b336f9-755e-4057-b9c5-c8b66570ffc5`.
  Shutdown capture took 11.48 seconds; both editors acknowledged `ready`, both exact
  TUI routes acknowledged selection, and no pending recovery panes remained.
  Additional dead-socket crash reconstruction and failed-placeholder retention
  regressions passed on laptop after reboot.

Laptop verification used staged feature files and isolated native databases to
preserve its different, uncommitted checkout and normal profile. Temporary units,
test applications, synced fixture and logind override were removed; original laptop
five-second delay restored. Permanent laptop enablement still requires deploying
this source/configuration normally. Evidence is retained in
`/tmp/opencode/tp-a19c7/summary.json` on PC and
`~/.local/state/terminal-persistence-acceptance-a19c7/` on laptop.
Final boot and follow-up regression evidence is in
`/tmp/opencode/tp-a19c7/final-summary.json`.

Application launches are acknowledged before success is recorded. A failed editor
or chat leaves an explicitly pending recovery pane; periodic saves and managed
destruction refuse to replace its saved workspace with a blank shell. Fix the
reported cause, exit that placeholder, then explicitly run
`context-checkpoint restore --context UUID --no-windows` or close/reopen the context.
Opening an already-open context still only switches to it. Neovim also refuses
autosave after failed startup recovery, preserving its prior directory session.

Remaining implementation/rollout work:

- The single-current v2 rewrite is implemented and locally tested; exact commands,
  results and deployment status are in `notes/SINGLE_CHECKPOINT_IMPLEMENTATION_RESULT.md`
  at the repository root. Historical device/reboot evidence above is for v1, not
  proof of a v2 fleet rollout.
- Non-tmux-only discovery and standalone terminal reconstruction are deferred by
  user decision; keep the current rewrite focused on checkpoint storage.
- All nine Home Manager and nine NixOS configurations evaluate. Actual fleet
  release still needs ARM package-build validation and a normal-profile canary;
  staged laptop tests did not reconcile or deploy its separate dirty checkout.
- Coherent local commits are complete; see `notes/COMMIT_HISTORY_RESULT.md` at the
  repository root for boundaries, checks and intentionally uncommitted preferences.
  Publication still requires pushing the Neovim submodule before the parent branch.
  No remote publication or fleet rollout was performed by the commit-history phase.

Known supported-scope limits:

- The current compositor exposes no native dwindle-tree serialization. Tiled
  insertion order/size is approximated and reported; floating geometry is normalized,
  clamped and relocated to a deterministic available monitor. Exact tiled trees or
  pixels are not promised.
- Grouped/shared windows are captured once per physical pane. A standalone
  ungrouped session consisting only of a window shared with another session may
  require manual linking; the unsupported case is reported and retained.
- Terminal processes without tmux attachments, arbitrary process memory, running
  tools/model requests, plugin/terminal editor processes, floating Neovim windows,
  OpenCode unsubmitted drafts, and Git snapshot/revert objects are not reconstructed.
  Their relevant limitations are reported; native conversation data is preserved.
- Git working-tree transfer remains separate and deferred. Recovery copies protect
  edited buffers, not the entire checkout. Other graphical-app adapters and sync
  indicator UI remain outside this milestone.
