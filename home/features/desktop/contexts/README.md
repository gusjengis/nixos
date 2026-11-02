# Persistent Desktop Contexts

Personal persistence layer above the reusable Hyprland `sessions` module. The
runtime module owns live workspaces/windows and exposes remembered logical views.
Notebook, synchronization, checkpoint and startup policy live in the personal
context layer rather than the reusable backend.

## Module selection

`desktopContexts.enable` defaults to `true`. Set it to `false` in a Home Manager
host module to use ordinary Hyprland workspaces without this persistence layer.
This disables context packages/services/timers, session initialization and
shortcuts, context-aware Git, tmux checkpoint hooks, and the Quickshell session
picker, organizer, and work widget. Quickshell does not load those surfaces or
watch their runtime state while disabled. Hyprland and numbered workspaces stay
enabled; existing context directories and notes are not deleted.

Home Manager materializes this choice into Hyprland's `host-features.lua` and
Quickshell's `features.json`; neither frontend chooses behavior by hostname.
`personalDesktop.enable` independently selects personal apps/integrations, while
`dev.enable` selects coding agents, development tools, and development repo sync.
Neovim, lazygit, and tmux remain core utilities with development disabled.

## Use

- `Super+Z`: switch between open runtime sessions only. Enter switches; unmatched
  searches never create sessions.
- `Super+Shift+Z`: Miller-column context organizer. Browse without launching;
  Enter opens/restores a context, reusing its existing runtime when already open.
- In the organizer, `Ctrl+N` creates in the focused column; `Ctrl+Shift+N` creates
  beneath the selected context. Creation does not open a runtime session.
- `Super+N`: context notebook. First open automatically shows it.
- `Super+T`: context terminal scratchpad; new tmux sessions start Neovim and OpenCode windows in its working directory, matching the session dispensary.
- `Super+Q`: another terminal attached to that context's tmux session.
- `Super+F`: file manager at the context working directory.
- `Ctrl+D` in runtime switcher: close running session, never delete saved context/notes.
- F2 in runtime switcher: rename runtime session only, not its saved directory.
- F2 in organizer: rename display label, including open/repository contexts.
  Physical directories and backend runtime names are preserved.

Contexts are directories under `~/sessions`, identified by `.context/context.json`.
Legacy nesting is inferred from directories. The organizer stores logical nesting
independently, so a context's tree location need not match its storage location.
Each has `.context/notes`, an independently openable Obsidian vault with nested
links to its logical children's notebooks. Its default opening view
is `Kanban.base`: **Thoughts → Todo → In-Progress → Done**. Obsidian saves edits
automatically. There is no desktop Save step or generated Home dashboard.

Git checkouts are embedded as `<context>/<repository>`, beside `.context`.
The context's `working_directory` can be a contained relative path, normally `.`
or the primary checkout's directory name, or an explicit absolute path such as
`/etc/nixos` or a mounted network job folder. There is no reserved `work` directory.
Absolute paths reference existing work without moving it into the context or
adding it to context synchronization or repository registrations. Context home,
notes and checkpoint storage stay in the original local context directory.
Notes/config stay outside the checkout and therefore outside its Git history.
Missing working directories fall back to the context directory; the notebook still opens.
All other ordinary files and folders beside checkouts are free-form synced work.

## Context organizer

The organizer uses Finder-style columns and the existing QuickShell macOS-like
typography/controls. A read-only right pane shows the selected context's resolved
configured working directory and `ls -al` output, including hidden files. Click
the path to edit it; use `.` to reset to context home. Relative paths also show
their full location, and unavailable targets show the fallback context folder.
Changing this setting does not move existing terminal panes or override restored
pane directories. Opening a context terminal or restoring its checkpoint refreshes
tmux's session working directory, so new windows use the configured working
directory rather than the directory used to stage restored panes.
Multiple contexts can share a working directory while keeping
separate UUID-keyed tmux sessions. Listings load
asynchronously as selection changes. Workspace and Kanban previews remain deferred.

| Input | Action |
| --- | --- |
| Up / Down | Select sibling; Shift extends selection |
| Right / Left | Enter children / return to parent |
| Enter | Open selected context; directory-only groups enter children |
| Type / Ctrl+F | Fuzzy search names and ancestor paths |
| Right in search | Reveal selected result in columns |
| Escape | Leave search, clear pending cut, or close menu |
| Ctrl+N / Ctrl+Shift+N | New sibling / new child |
| F2 | Rename display label |
| Ctrl+M | Searchable move destination chooser |
| Ctrl+X / Ctrl+V | Cut selection / paste into focused column |
| Ctrl+A | Select all siblings in focused column |
| Ctrl+Z | Undo move or rename |
| Ctrl+D | Confirm moving selected closed contexts to system Trash |

Ctrl-click toggles selection; Shift-click selects a range. Drag onto a context to
nest beneath it, or into column space to move to that level. Hover during a drag
reveals children. To paste beneath a selected context, first press Right to enter
its column, then Ctrl+V. The destination chooser also includes Top level.

Column width is adjustable by dragging dividers or using the header's minus/plus
controls. Width, last selection and per-parent child selections persist locally in
`$XDG_STATE_HOME/desktop-contexts/organizer.ini`; browsing returns to remembered rows.
Existing directory-only groups remain navigable; **Make context** adds a notebook
and persistent identity to that group without moving its children or repositories.

`~/sessions/.context-layout.json` is the synchronized source of organizational
labels and parent relationships, keyed by stable context UUID (deterministic IDs
for legacy directory groups). One atomic file makes batch moves indivisible.
Unknown IDs are retained for incoming contexts; missing-parent contexts remain
visible at top level with a warning badge. Cycles and destination label collisions
are rejected. Syncthing conflict files block organization until resolved.

Undo retains at most 30 moves/renames locally and refuses to overwrite intervening
layout edits from another device. Creating a context or converting a group clears
undo history: undo never deletes a newly created notebook. Moving/renaming never
changes working directories, checkout registrations, checkpoint IDs or live tmux
sessions. No working-directory or mode inheritance is introduced here.

**Delete… / Ctrl+D** names the selected contexts and defaults focus to Cancel.
Explicit confirmation moves their entire directories (files, checkout, notebook,
saved state) to system Trash via `gio trash`; the organizer never permanently
unlinks them. Close running contexts and notebook windows first. Move logical
children out first; deletion also refuses physical directories containing other
contexts even when those contexts were logically reparented elsewhere. Batch
deletion validates all targets before moving any files. Restore through the file
manager's Trash; dormant UUID layout entries retain a restored context's label and
parent. Deletion clears layout undo. Historical Git sync exclusions and `dev.list`
entries remain intact; repo sync can recreate a checkout directory, but cannot
recreate the deleted notebook/context identity.

The legacy `contextctl rename` still means physical directory rename and retains
its restrictions. Organizer commands are separate:

```sh
contextctl organize create "Hardware"
contextctl organize create "Keyboards" --parent PARENT_UUID
contextctl organize rename CONTEXT_UUID "New display name"
contextctl organize move CONTEXT_UUID OTHER_UUID --parent PARENT_UUID
contextctl organize move CONTEXT_UUID  # top level
contextctl organize promote GROUP_ID
contextctl organize undo
contextctl organize delete CONTEXT_UUID --confirm
```

Organization tests: `test_organization.py`. UI/model checks (unused compositor
signature prevents acting on the real desktop):

```sh
HYPRLAND_INSTANCE_SIGNATURE=organizer-test timeout 15 qs -p home/features/desktop/quickshell/test_context_organizer.qml
```

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

## Context-owned OpenCode history

OpenCode launched from a context terminal receives its stable context UUID and
context home independently of the pane's working directory. Several contexts can
work in `/etc/nixos` without sharing their own chat lists or tmux sessions.

- New conversations belong to the launching context. Subagents inherit their
  conversation's owner; forks retain that owner but get a separate conversation
  identity. Ordinary metadata updates cannot transfer ownership.
- The native session picker, search and quick-switch list show this context plus
  logical descendants whose **configured canonical working directory** matches.
  Siblings and parents are not implicitly visible. Missing directories are compared
  by configured target, not their temporary fallback. Reparenting or changing a
  work directory updates visibility through the catalog watcher without restarting
  OpenCode. Parent picker rows show the originating context's breadcrumb.
- Resuming a child conversation from a parent updates the **child's** library.
  Parent terminal checkpoints store a UUID/conversation/member reference, not a
  second copy of the child's conversation or attachments.
- All owned conversation families, including historical chats with no open pane,
  are exported under `<owner>/.context/state/chats/`. This uses the same atomic,
  chunk-addressed current-root store and divergence protection as terminal recovery.
  Native SQLite remains a machine-local working index; it is not synchronized.
- The checkpoint timer runs 30 seconds after the previous run finishes and exports
  local library changes; it does not import historical libraries in the background.
  Background checkpoint work is limited to 25% of one CPU, with a 15-minute overall
  deadline. Managed terminal checkpoint/close also saves selected owned chats
  independently of that background CPU limit. Launch publishes local metadata-only
  visibility without probing external working directories or waiting for the library
  lock. A server plugin imports visible portable libraries in the background,
  initializing a fresh native database when needed. Fresh conversation families
  created by this server send immediately; existing chats wait for preparation;
  preparation errors and superseded conversation roots reject sends rather than
  silently continuing stale history. The session picker queries the native index
  when opened, including newly imported conversations. The command
  palette's **Sync portable context chat libraries** refreshes the launching context's
  visible libraries. CLI helper commands such as `db path` bypass launch preparation.
- Library checks read the archive index before accessing conversation history.
  Unchanged history stays lazy; accessed objects and archive publication still
  receive integrity checks. Successful library checks are reused only within one
  checkpoint, and verified imports persist progress per conversation.
- Context-home paths and external work-root paths relocate independently. The
  repository/job folder must be available at its configured local location; the
  library carries chat records and supported attachments, not the repository itself.
- Native IDs can change during conflict-safe import. Stable ownership and logical
  conversation/member IDs survive that remapping. Old native copies are retained
  but excluded from scoped lists. Native deletions publish portable tombstones.
- Concurrent native and incoming portable edits stop library synchronization with
  both copies retained. There is no silent merge or last-writer overwrite.

Existing untagged history is not assigned by guessing from its working directory.
Use the OpenCode command palette's **Browse unowned conversations to assign to this
context**, or **Assign unowned conversation to this context** for the current chat.
Assignment is explicit and includes its subagents. An already owned conversation
cannot be moved by opening it from another context.

Without context identity, OpenCode retains its ordinary global/project behavior.
The pinned OpenCode source has a small ownership/list-filter patch; the launcher
and portable library live in this repository. Updating the upstream pin requires
rechecking patch applicability and the native context-session acceptance tests.
Quit and restart existing OpenCode instances after deployment; running instances
retain their old executable and plugins.

Native acceptance (isolated fixture databases, no model calls):

```sh
PERSISTENCE_NATIVE_TESTS=1 python3 -B -m unittest discover -s home/features/desktop/contexts -p test_context_chat_library.py -v
PERSISTENCE_NATIVE_TESTS=1 python3 -B -m unittest discover -s home/features/desktop/contexts -p test_native_context_sessions.py -v
```

## Notebook Kanban

New contexts receive the shared `notebook/Kanban.base` view and the repository-owned
Context Notebook plugin. Ordinary Markdown notes anywhere in the vault are cards;
new notes are created at the vault root with `status: Thoughts`. Dragging cards uses
native Bases to update `status`. `Templates/`, `Attachments/`, hidden paths, and notes
with `kanban: false` are excluded. Obsidian 1.14 or later is required.

Each card stores `created` and append-only `kanban-history` entries containing
`status`, UTC ISO-8601 `at`, and `event`. Live creation and transitions use `entered`;
initial migration uses `observed`, since historical phase-entry times are unknown.
Returning to a phase appends another entry. Existing creation dates are preserved;
filesystem-derived dates have an explicit `created-source` estimate marker.

`contextctl setup-notebooks` retrofits existing context vaults. It merges required
settings, preserves existing custom views and card bodies, and links the plugin
directory to editable repository code. Empty Home scaffolding moves to vault Trash;
Home notes with real content become ordinary `Notebook Notes` cards. New contexts
and previously unconfigured vaults use the same setup automatically. The context
launcher enables the installed plugin in its own closed local profile; an already
open notebook needs one close/reopen after initial deployment.

The plugin opens Kanban on every cold startup and provides **Open context Kanban**
in the command palette. Ordinary notebook scratchpad toggles keep the current view.
It records metadata while Obsidian is running and catches up on incoming notes at
startup; intermediate edits made entirely outside a running notebook are not a
historical audit log. Shared content/status/history sync; Electron profiles stay local.

### Nested notebooks

Each original notebook contains **relative directory symlinks to immediate child
notebooks**, named with the labels in the context organizer. Following those links
shows grandchildren at their proper depth; descendants are not mounted a second
time at the parent root. Directory-only organizational groups become generated
folders containing their children's links. Notes are never copied or rehomed.

The main **Kanban** view includes descendants and displays a **Context** breadcrumb
on each card. **This context** uses the same board with child folders excluded.
New root notes still belong to the notebook where they were created. Templates,
attachments and hidden support files remain excluded at every depth. Existing
custom boards/views and presentation settings are preserved; hierarchy-owned
Context formulas and the This context filter follow the current tree.

`contextctl notes --global` opens `~/sessions/.context/notes` in its own isolated
Obsidian profile, with the full hierarchy nested beneath it. This is an explicit
global view, not a fallback for conversations without a saved owning context.

Create, rename, move, promote, undo and delete commands reconcile notebook links
after catalog publication, outside the global mutation lock. The existing catalog
watcher handles incoming layout changes and periodically repairs generated entries.
`.obsidian/context-hierarchy.json` records managed links and empty group folders;
only matching managed symlinks and empty generated folders are removed. Colliding
user files/folders and manually redirected links are retained and reported.

The shared plugin refreshes Obsidian's index after mount changes, clearing stale
nested watchers that otherwise prevent renamed symlinks from being indexed. This
small adapter integration is covered by native Obsidian acceptance and must be
rechecked when upgrading Obsidian. Metadata observations use `context-notes observe`
and the original owner's lock, avoiding cached frontmatter writes from independent
parent/child profiles racing over the same note.

Agent list/search/brief and the desktop work widget include descendants with stable
owner IDs, owner-relative paths and context labels. Agent updates use the original
owner's lock/revision checks; opening a nested card keeps it in the active parent's
Obsidian profile. Unmanaged symlink escapes and stale moved-child paths are rejected.
The underlying list API also accepts `local_only: true`.

Proof: `test_notebook_hierarchy.py` covers lifecycle reconciliation, groups, global
aggregation, collisions, idempotence and owner routing. With `NOTEBOOK_NATIVE_TESTS=1`,
`test_notebook_native.py` verifies nested indexing, recursive/local Kanban, context
labels, two open profiles, phase history, external atomic edits, links/attachments,
live rename/reparent/create, URI routing and reopen.

### Context dictation

Ctrl-dictation keeps Handy's existing transcription flow, but writes an ordinary
Thoughts note into the focused saved context's `.context/notes/` root. The popup
queries the live context at recording start and retains that UUID through saving;
switching sessions during transcription does not redirect the note. No saved
context means no note, with no fallback to the central vault.

`context-notes capture` accepts JSON `{ "body": "..." }` with an explicit
`--context UUID`. It saves immediately under a unique temporary title, then asks
Omega's `qwen3.8:27b` for a title in a detached worker. Naming preserves note bytes,
never replaces an existing filename, and skips notes manually edited or renamed.
An unavailable model leaves the temporary note intact.

Focused proof: `python3 -B -m unittest test_context_dictation test_context_notes`.
The native popup writer test requires a running Wayland desktop.

### Agent-assisted notebook

OpenCode's `context-notebook` skill and server plugin live beside its owning module
at `home/features/agents/opencode/notebook/`. Home Manager links them into the global
OpenCode configuration. Quit/restart OpenCode after deploying or changing them.

The bootstrap resolves `session.metadata.desktop_context.id`, never cwd or desktop
focus. It loads the workflow and notebook identity; the agent then obtains a
permission-checked bounded briefing through `notebook_read` before its first reply.
Note bodies stay out of the bootstrap and are retrieved only when relevant. The
briefing is a tool result in chat history, not a full-vault prompt dump. A user turn
after a 30-minute gap requests fresh orientation; no background refresh/model calls.

`notebook_read` offers brief/list/search/read, with pagination. `notebook_write`
offers create/update for recognizable conversation-derived thoughts and meaningful
work. It uses normal external-directory/edit permissions; plan and delegated agents
cannot write. Unowned/unavailable contexts have no notebook fallback. Internal
title/compaction prompts do not receive the notebook bootstrap.

Active cards explicitly read or written in a conversation get a closeout reminder
in subsequent primary-agent prompts and compaction context. Before finishing,
the agent rereads relevant cards and explicitly writes `status: "Done"` for
verified completed outcomes; changing only Work state or chat todos does not
change notebook status. The coordinator reconciles delegated completion reports.
Partial outcomes keep their blockers; no status is inferred automatically.

Both tools call `context-notes --context UUID COMMAND`, a JSON-stdin/stdout helper.
Writes work with Obsidian closed. Updates require the SHA-256 revision from a fresh
read, use a machine-local writer lock, and check again immediately before atomic
publication. This is optimistic edit protection, not a cross-device lock. Existing
note bodies and unrelated YAML are preserved; a delimited Work state section holds
brief decisions, current state and next action. Phase/history update together;
Obsidian observes an already-recorded transition without duplicating it.

The bottom-right QuickShell desktop widget displays the active saved context's
Todo cards above In-Progress cards, refreshing every five seconds. It grows to
fit the board up to available screen height, without a fixed row/560px cap.
`Super+Shift+K` toggles it; visibility survives QuickShell reloads. It lives on the top layer,
reserves no workspace space, and follows workspace switches above application windows.
Long lists scroll, initially positioned at the active-work end; In-Progress cards
are never truncated. Runtime-only sessions show no widget. Ownership comes from
`DesktopSessions.contextCatalog.active_context`, never the working directory.
Card clicks use `context-notes --context UUID open` with a JSON `path`, targeting
that context's isolated Obsidian profile and revealing its notes workspace.
Stale clicks after a context switch are rejected. Appearance and reader live in
`quickshell/config/InProgressWidget.qml` and `InProgressModel.qml`; native reader
acceptance is `python3 -B -m unittest test_in_progress -q` from `quickshell/`,
using a Python environment with PyYAML.

The widget renders after workspace and special-workspace blur and uses the
existing Hyprglass Liquid Glass material. It needs no `no_workspace_blur`
exemption, which would also expose sharp wallpaper beneath its translucent body.

Context desktop files live on a separate bottom-layer QuickShell surface, above
wallpaper and behind application windows. `ContextDesktop.qml` reads the active
saved context node's `path`, not `cwd` or `working_directory_path`; hidden entries
including `.context` never appear. Listings refresh every 2.5 seconds, clear
immediately on owner changes, and discard late previous-owner responses.
`DesktopSurface.qml` uses the extracted MacOS-Native MIME/folder/application icons,
48px icons and 12px labels by default, and columns arranged from the upper right.
Selection supports click, Ctrl/Shift-click, marquee, Ctrl+A, arrow keys, and Escape;
double-click or Enter opens selected entries, and Delete moves them to Trash.
Application `.desktop` shortcuts launch only on explicit Open. Empty-space
right-click offers New Folder (also Ctrl+Shift+N), Open Desktop Folder, wallpaper,
sorting, and 32/48/64px icon sizes. File right-click offers Open and Trash. Sort
and icon-size preferences survive shell reloads; placement is grid-based, with
horizontal wheel scrolling when columns exceed screen width. Rename, arbitrary
icon placement, and drag/drop file transfer remain file-manager operations.
The packaged `context-desktop-files` helper takes literal argument arrays, creates
uniquely named folders without replacing existing files, and uses `gio trash`
instead of permanent deletion. Focused checks from `quickshell/`:

```sh
python3 -B -m unittest test_desktop_files -v
quickshell -p test_desktop.qml
```

Example CLI read (the tools handle this automatically):

```sh
context-notes --context CONTEXT_UUID brief </dev/null
```

Focused integration checks:

```sh
python3 -B -m unittest test_context_notes test_notebook -q
node ../../agents/opencode/notebook/runtime.test.mjs
NOTEBOOK_NATIVE_TESTS=1 python3 -B -m unittest test_notebook_native -v
NOTEBOOK_OPENCODE_NATIVE=1 NOTEBOOK_OPENCODE_BINARY=/path/to/native/opencode python3 -B -m unittest test_notebook_opencode -v
```

Native OpenCode acceptance uses a local scripted OpenAI-compatible endpoint, not
remote inference. It checks real hook injection, tool schemas/execution and plan
write rejection. Skill conversation scenarios are in `notebook/evals/evals.json`
beside the OpenCode skill; those are human-review scenarios, not scored model results.

Focused checks:

```sh
python3 -B -m unittest test_notebook test_contextctl test_organization -q
node notebook/test_plugin.cjs
NOTEBOOK_NATIVE_TESTS=1 python3 -B -m unittest test_notebook_native -v
```

## Implementation

`contextctl watch` observes the backend's atomically published JSON snapshot,
records active context changes locally, and publishes a separate picker catalog.
No personal policy or hooks execute inside the reusable session backend.
`session-env-sync` starts the watcher with the current compositor environment.

`contextctl create NAME [--open]`, `list`, `open UUID`, `rename UUID NEW_LEAF`,
`notes`, `terminal`, and `files` are available independently of the picker.
`contextctl set-working-directory UUID PATH` updates the same working-directory
setting shown in the organizer. Paths sync with context metadata; unavailable
paths on another computer fall back to its context home.
Launch commands can receive `--runtime ID` to bind delayed scratchpad launches
to their originating session rather than whichever context is now active.

Each notebook uses a local, UUID-keyed Electron profile. Window ownership follows
the process profile (native Wayland ignores the requested custom class), not
ambiguous titles. The notebook plugin opens Kanban after native workspace loading,
preserving the remaining saved workspace. No startup URI is needed, avoiding a vault
loading race observed during testing. Existing global Obsidian settings stay
untouched. Profiles are not synced. Extra processes use more memory than multiple
vault windows sharing one process.

Each profile also gets a private `XDG_RUNTIME_DIR` under the session runtime,
with `WAYLAND_DISPLAY` made absolute to preserve compositor access. Obsidian
1.14.5 otherwise unlinks/rebinds one shared `.obsidian-cli.sock` regardless of
`--user-data-dir`, so concurrent contexts can steal note-opening commands from
each other. Both initial launches and later URI requests use the same private
runtime. Already-running profiles need one normal restart after this change.
Native tests use temporary private runtimes too; they must never replace the
desktop's socket. `OBSIDIAN_TEST_ASAR` optionally tests a locally downloaded app
update. Native coverage opens a note with another profile running and again
after that profile exits, checking the actual active file each time.

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
  at most three attempts within one two-second deadline; normal capture
  uses one snapshot RPC. A bounded fast `nvim_get_mode` RPC checks readiness first,
  even when a pending key sequence blocks ordinary evaluation. An input-blocked
  editor is skipped without blocking the context's save or managed close.
  Malformed replies, native errors and schema/identity mismatches likewise discard
  only that editor's saved session. A subsequent healthy capture can save it again.
  Background checkpoint/restore diagnostics go to the journal/events log, never
  desktop notifications.
- New chunks are flushed before atomic root replacement. A machine-local pending
  journal lists owned new/retired objects; recovery either keeps the valid committed
  root or reports missing/corrupt data explicitly. There is no older-root selection.
  Independent recoverable panes/windows/sessions still continue.
- `$XDG_STATE_HOME/desktop-contexts/terminal/stores/<context-id>/` holds one local
  witness/index, its incrementally updated object mirror, and at most one pending
  transaction. The mirror protects local divergent bytes against synced deletions;
  it is never silently substituted for incomplete synced state. Unowned tmux
  sessions use `terminal/unowned/terminal/` with the same current-root policy.
  Live tmux sessions claiming a context UUID no longer in the catalog are captured
  there too, with `orphaned_context_id` retained and an explicit recovery warning.
  This preserves their panes without recreating deleted contexts or blocking
  checkpoints/closure of unrelated contexts.
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

Neovim uses its built-in `:mksession`/`:source` support for file names, tabs,
splits, folds and cursor positions. Standalone periodic/exit saves atomically
replace `.context/state/nvim/sessions/<directory-key>.vim` (or its XDG fallback).
The last saving editor owns that directory session; coordinator checkpoints still
capture each editor independently as a version-3 `editor.json` plus `session.vim`.
Unsaved text, unnamed-buffer contents, terminals and plugin options are not saved.
No recovered-buffer copies or custom buffer-object stores are created.

Failed saves remove the stale directory session; failed restores discard that
session and start fresh. Explicit file/stdin launches take precedence over automatic
restore. Errors are logged quietly to Neovim's `context-nvim/sessions.log`, with
identical errors logged once per editor lifetime, never `vim.notify` or hit-enter
prompts. Old version-1/2 buffer recovery is not loaded. Failed editor acknowledgement
clears the pending marker and does not retain/block the whole terminal session.
Only explicitly removed editor artifacts may bypass validation of the previous
checkpoint; all remaining chat/workspace artifacts and the new root remain checked.

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

Managed close captures application state outside the global context mutation lock.
A nonblocking runtime-specific lock rejects duplicate close attempts. The picker
runs closure in a separate background process and releases its foreground action
slot immediately; the session remains marked closing while capture runs. Catalog
updates, other context switches, and terminal/file/note launches remain available.
Windows are still closed only after a successful checkpoint; capture failure leaves
the runtime intact. This fixes close-induced launcher freezes, not restore latency
or the time required by individual capture adapters.

Regression proof: `test_contextctl.py` holds a checkpoint pending in a separate
process while catalog, terminal/file/note launches and another context switch finish;
duplicate close is rejected. `../quickshell/test_session_close.qml` uses an isolated
slow command fixture to verify picker reopening and independent foreground switching.
On 2026-10-21, a disposable Mac runtime with a real isolated tmux server passed
save-before-close and artifact validation; catalog took 0.076s and switching 0.126s
while closure was deliberately held pending. T480s passed all 52 context tests and
was updated with `rehome t480s`; its unresponsive compositor prevented live UI tests.

Restore startup also runs outside the global context mutation lock. The picker uses
`contextctl open UUID --background` (or `create NAME --open --background`): success
means the runtime/mapping is ready and a detached application-restore worker has
been launched, not that every application has finished loading. Synchronous CLI
opening remains available by omitting `--background`. Worker failures are logged
and notified through the existing terminal-recovery reporting path.

Long reconstruction holds a context-specific persistence lock, shared with that
context's checkpoint publication, instead of the global checkpoint/lifecycle lock.
A runtime operation guard prevents managed closure during reconstruction; reopening
the same mapped context only switches to it, without another restore. Unrelated
contexts can update their catalog, launch applications, and switch while an adapter
is waiting. Window placement can inspect `sessions.state(runtime_id)` without
activating that runtime. Saved view/focus is applied only if it is still active,
so late background restoration does not explicitly switch the user back.

Restore-blocking regression was reproduced before the fix on Mac using isolated
processes and a paused application adapter. Afterward Mac passed 83 context,
organization and checkpoint-store tests; T480s passed 62 native persistence tests.
A detached-worker test proves early return, mapping reuse, and close exclusion;
headless QML covers background open/create requests. Lua engine/placement tests
cover hidden-session workspace inspection and focus preservation. Live compositor
testing was unavailable during this verification; these are isolated/headless and
native-tmux results, not a live desktop acceptance claim.

Restoration waits for new shells/supported programs to execute before acknowledging
success and clearing failed-restore retention. A forked tmux child is not yet proof
that the requested process started. Missing/failed process acknowledgement remains
an explicit, retained recovery failure.

The Nix tmux overlay distinguishes explicit tab removal from session archival:

- `kill-window` and `kill-pane` start an independently owned close worker. The
  originating client queue does not wait for application capture. Only the target
  session is inventoried; ordinary closes do not sweep chat libraries, checkpoint
  other sessions, or check external working-directory availability.
- Requested panes receive small, fsynced machine-local deletion records before
  moving to a detached `__context_closing_<request>` session. The original client
  immediately regains its remaining tabs. Shell/monitor panes require no exporter.
  Editors/chats capture only their own recovery data before process teardown.
  Private staging sessions/windows are excluded from periodic snapshots.
- Local deletion records live under
  `$XDG_STATE_HOME/desktop-contexts/terminal/closures/<context-id>/`; additive synced
  records live in `<context>/.context/state/terminal/closed/<pane-uuid>.json`.
  Both checkpoint merging and restoration filter these IDs, so a stale checkpoint
  or legacy retained layout cannot resurrect explicitly closed tabs. Closing the
  last tab has the same forgetting semantics. Native linked windows are related
  targets: their links and deletion records are removed across their owners, but
  those owners' application state is not captured.
- Unsaved editor snapshots and chat recovery references are separate from window
  restoration, under the machine-local `terminal/closed-work/<request>/` directory.
  `request.json` records ownership; `status.json` records success/failure. Capture
  failure preserves the private processes and reports a retry command:
  `context-checkpoint retry-close --request <request>`. Recovery buffers are never
  silently written over original editor files.
- `kill-session` and `kill-server`, including tree-mode tagged `X`, still archive
  remaining layout before destruction. Their originating queue waits while the
  event loop answers helper queries. Targeted session archival captures only the
  requested session/group on its server and preserves other sessions' last saved
  records without contacting their adapters. Failure, timeout, replacement targets,
  and changed server topology cancel destruction. The archive helper has a
  90-second limit.

Prefix `k`, `&`, and `x` use background close bindings so reloading `tmux.conf`
also fixes existing servers. Notification-dismissal hooks run in the background.
Native aliases, command-line calls and tree-mode window/pane deletion use the new
dispatcher once the running server uses the rebuilt tmux executable; installing a
package cannot replace an already-running server process.

Regression proof includes actual originating-client keyboard input while a close
helper is held pending, background capture after the tab is hidden, exporter failure
and retry, stale/retained snapshot filtering, last-tab/pane deletion, linked-window
removal, offline unrelated working directories, and scoped whole-session archival.

Tmux inventory reads stable session/window/pane IDs directly in its three list
formats. Missing IDs and ownership environment updates are sent in batches of at
most 64 commands, with physical IDs deduplicated for grouped/linked windows and
panes. Every batch must succeed before capture returns; checkpoint publication and
the native pre-destruction barrier are unchanged.

Measured on 2026-10-21 with 48 shell-only sessions on an isolated server, a repeated
targeted pre-kill checkpoint went from 436 tmux subprocesses to 7. Mac elapsed time
fell from 0.698s to 0.034s; T480s from 1.162s to 0.047s. These measure inventory-heavy
fixtures, not editor/chat-heavy sessions or compositor timeouts. T480s passed all
62 persistence tests; Mac passed 13 native barrier tests, including actual keyboard
input in another attached client while a checkpoint was held pending. Restoration,
failure/timeout cancellation, grouped/linked identity preservation, and native
kill-session/window/pane paths are covered by those suites.
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

### Foreground latency and discovery boundaries

Selected operations use a root-specific, machine-local UUID/path index in
`desktop-contexts/index-*.json`. Each use validates the selected owner's current
metadata and vault; changed UUIDs, redirected paths, and stale entries never claim
another owner. Discovery reconciles synced/moved directories. Cold discovery and
hierarchy validation remain metadata-only. Selected work-root checks wait at most
150ms outside the shared mutation lock, falling back to context home when slow.

The watcher discovers metadata outside the foreground lock every ten seconds.
Runtime updates reuse that snapshot; discovery/layout changes trigger scope
refresh. Open, close, terminal, notebook/card and selected-chat paths do not rebuild
the catalog. Create/rename registrations invalidate cached discovery promptly.

Targeted saves use the context/server ownership index, saved backing servers, and
explicit sockets. Only owned sessions are inventoried; legacy unclaimed sessions
may need local-ancestor inference. New managed terminals use the default server;
custom-server saves can specify `--socket`. Runtime-only closure resolves terminal
attachments before pane inventory, retaining other machine-local saved sessions.
Close revalidates runtime ownership after saving and before destruction.
Checkpoint publication is serialized per context. Lifecycle updates use a short
metadata lock, so another context's large publication cannot block opening work
or invalidate an unrelated snapshot.

One-pane chat capture queries its selected native session/family and direct owner.
Foreground close performs no closed-library sweep. Periodic maintenance compares
lightweight native-owner/head tokens, handles at most eight dirty owners using four
independent workers, and audits one owner per minute for dependencies not reflected
in native timestamps. Affected scopes read only their visible owners' rows/ledgers.
Pending recovery shells fail preflight before expensive adapter work, retaining
their saved recovery data.

Restore builds local loading panes and maps terminal windows before imports,
external pane-directory checks, or app readiness. Up to sixteen pane startups
run independently; pending markers clear only after real acknowledgement. Failures
retain saved sessions instead of allowing recovery shells to replace their data.

Regression gates: `test_context_performance.py` and isolated native persistence,
chat-library and tab-close suites with `PERSISTENCE_NATIVE_TESTS=1`.

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

Native capture regressions can be run without the retired tmux-resurrect plugin:

```sh
PERSISTENCE_NATIVE_TESTS=1 python -B -m unittest discover -s home/features/desktop/contexts -p test_persistence.py -v
PERSISTENCE_NATIVE_TESTS=1 python -B -m unittest discover -s home/features/desktop/contexts -p test_chat_portability.py -v
```

OpenCode CLI stdout is captured through an anonymous regular file: its explicit
exit can truncate large piped JSON exports despite returning success. Unchanged
captures still skip the CLI. Successful saves notify only newly introduced,
distinct warnings; existing caveats remain recorded in the checkpoint manifest.
If a chat changes during a periodic export, the previous checkpoint remains
untouched and the timer retries on its next tick without a failure notification.
Manual, close, shutdown, and pre-destruction captures still fail visibly in that
case rather than publishing an inconsistent snapshot.

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

Application launches are acknowledged before success is recorded. Failed editor
sessions are now disposable: the pending marker clears, the failed session is
dropped, and other windows continue. No unsaved-buffer recovery is attempted.
A failed chat still leaves an explicitly pending recovery pane; periodic saves
and managed destruction refuse to replace its saved workspace with a blank shell.
Fix the logged cause, exit that placeholder, then explicitly run
`context-checkpoint restore --context UUID --no-windows` or close/reopen the context.
Opening an already-open context still only switches to it. Neovim can save a fresh
file/layout session immediately after discarding a failed restoration.

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
