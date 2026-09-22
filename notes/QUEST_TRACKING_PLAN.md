# Quest Tracking System Plan

The task model is not a tree, but a directed acyclic graph. Tasks are shared
nodes; parent-child links form the graph.

## Proposed Semantics

- Task owns title, description, completion, priority, deadline, reminders, and recurrence.
- Parent-child link means "task contributes to goal."
- One task may have many parents and children.
- Completing task updates every appearance globally.
- Completing parent remains manual; children do not auto-complete it.
- Cycles are forbidden.
- Pinned task becomes quest-log root, even if it also has parents.
- Active quest means pinned and incomplete.
- Progress means completed unique descendants divided by all unique descendants.
- Shared descendants display under every relevant path but count once per quest's progress.
- Child order initially uses priority descending, deadline ascending, then ID ascending.
- No per-parent state or ordering exists in MVP.

Example:

```text
[ ] Improve health                         3/7
    [x] Buy running shoes
    [ ] Exercise consistently
        [x] Choose workout plan
        [ ] Run three times weekly

[ ] Prepare for hiking trip                2/5
    [x] Buy running shoes        shared
    [ ] Book campsite
```

Checking "Buy running shoes" changes both appearances.

## Backend Choice

Use Vikunja first.

Current Vikunja supports:

- Many-to-many parent/subtask relations
- Arbitrary nesting
- Cycle rejection
- Recursive descendant expansion
- Global task completion
- Favorites suitable for pins
- Priority, deadlines, reminders, and recurrence
- API tokens
- Responsive web/PWA interface
- Email reminders
- Cross-project relations

Main mismatch: relation edges have no per-parent ordering. This is acceptable
for MVP.

Taskwarrior has multiple dependencies and a strong CLI workflow, but mobile,
reminders, nested rendering, and server-facing APIs would require more custom
work. A custom backend would mean rebuilding substantial solved
infrastructure.

## Architecture

```text
                    Vikunja on alpha
                    SQLite + attachments
                    localhost:3456
                           |
                  Tailscale Serve HTTPS
                           |
           +---------------+----------------+
           |               |                |
       quest CLI      Android browser    Vikunja web
           |
      quest core
     traversal/API
       /       \
Quickshell     future TUI
                   |
              future MCP
                   |
          agents / voice input
```

No adapter daemon initially. CLI execution matches existing Quickshell
JSON-helper architecture.

Create a daemon only if:

- Quest tree exceeds roughly 200 ms.
- API traversal becomes request-heavy.
- Live updates become necessary.
- Per-parent ordering or edge metadata gets added.

## CLI Design

Human output is default; stable versioned JSON is available through `--json`.

```bash
quest log
quest roots
quest tree <task>
quest show <task>

quest add "Improve health"
quest add "Buy running shoes" --parent <task>
quest attach <child> --to <parent>
quest detach <child> --from <parent>

quest done <task>
quest reopen <task>
quest pin <task>
quest unpin <task>

quest edit <task> --priority high
quest edit <task> --due 2026-10-01T17:00:00-07:00
quest remind <task> --at 2026-09-30T09:00:00-07:00

quest search "shoes"
quest capture "Buy milk" --parent shopping
quest doctor
```

`quest` hides Vikunja relation-direction details. Users and agents always speak
in parent/child terms.

JSON envelope:

```json
{
  "schema": 1,
  "data": {}
}
```

Quickshell-specific output should include flattened occurrences:

```json
{
  "task_id": 42,
  "path": [1, 8, 42],
  "depth": 2,
  "shared": true,
  "done": false,
  "title": "Buy running shoes"
}
```

Flattening belongs in quest core, not QML.

## Implementation Plan

### Phase 1: Vikunja Service

Add a host-local module such as `system/hosts/alpha/vikunja.nix`.

- Pin a known Vikunja version.
- Enable the native NixOS service if its package and module support the required version.
- Bind the service to localhost only.
- Store database and attachments beneath `/data/.services/vikunja`.
- Use SQLite on local Btrfs.
- Set the public URL exactly to the Tailscale HTTPS address.
- Expose private HTTPS with Tailscale Serve on an unused port, likely `8444`.
- Keep Funnel disabled.
- Configure SMTP through external root-readable credentials, never the repository.
- Add the service to fleet monitoring.
- Add consistent SQLite backup using `sqlite3 .backup`, plus attachment backup.
- Require `/data` before service startup.

Example endpoint:

```text
https://alpha.tail29bd65.ts.net:8444/
```

### Phase 2: Compatibility Spike

Before writing permanent client code, create a scratch project and prove:

1. Task C can be a child of both A and B.
2. C appears under both roots.
3. A -> B -> C -> A is rejected.
4. Arbitrary depth expands correctly.
5. Completing C updates both appearances.
6. Completing A leaves children unchanged.
7. Unlink removes the inverse relation cleanly.
8. An API token can create and delete relations.
9. Favorites can fetch pinned roots with descendants.
10. Completed descendants remain retrievable.
11. A 200-task graph performs acceptably.
12. A reminder email reaches the mailbox.
13. Android over Tailscale can add and complete tasks.

Go/no-go: replace Vikunja only if shared graph behavior fails these checks.

### Phase 3: Quest Core And CLI

Create a Home Manager application feature, likely:

```text
home/features/applications/quest/
|-- default.nix
|-- quest.py
|-- quest_core.py
`-- test_quest.py
```

Responsibilities:

- Vikunja API v2 adapter
- Authentication and version check
- DAG traversal with visited-set protection
- Shared-node detection
- Unique-descendant progress
- Stable flattening for UI consumers
- Human and JSON output
- Clear conflict, network, and authentication errors
- `quest doctor` consistency checks

Configuration:

```text
~/.config/quest/config.json
~/.config/secrets/quest-token
```

Token file mode is `0600`; never pass the token through process arguments.

Initial commands:

- Read: `log`, `roots`, `tree`, `show`, `search`
- Write: `add`, `attach`, `detach`, `done`, `reopen`, `pin`, `unpin`
- Metadata: `edit`, `remind`
- Maintenance: `doctor`

Do not add natural-language date parsing yet. Use explicit timestamps first.

### Phase 4: Quickshell Quest Log

Follow the existing service/helper split:

```text
config/bar/QuestService.qml
config/bar/components/QuestLog.qml
config/bar/components/QuestPopup.qml
```

Likely integration points:

- Instantiate the service once in `Bar.qml`.
- Add a quest button to `BarWindow.qml`.
- Add an IPC toggle.
- Run `quest --json log`.
- Refresh when opened, after mutation, and periodically.
- Render each pinned root as a quest card.
- Show nested flattened rows, priority, deadline, shared indicator, and progress.
- Include completed children, visually subdued.
- Have checkbox invoke the CLI, then refresh all occurrences.
- Preserve the last valid state during network failures.
- Show a stale/offline indicator rather than blanking the panel.

Start as a popup. A persistent WoW-style desktop tracker can follow after the
interaction proves useful.

### Phase 5: Android Workflow

- Install the Vikunja PWA through the browser.
- Access it through Android Tailscale.
- Validate task capture, completion, deadlines, and reminder editing.
- Use email reminders initially.
- Add a home-screen shortcut.
- Do not depend on the experimental native app for MVP.

If email proves too weak, add `ntfy` delivery later rather than making native
push block the core system.

### Phase 6: TUI

Build only after the CLI workflow stabilizes.

- Reuse quest core directly.
- Use Vim navigation: `j/k`, `h/l`, `gg/G`.
- Use `x` to complete, `p` to pin, and `a` to add a child.
- Support searching for and linking an existing task.
- Expand and collapse branches.
- Show shared-node indicators and parent lists.
- Run naturally inside a Neovim terminal.

This avoids fragile magic-buffer synchronization while retaining a Neovim
workflow.

### Phase 7: MCP And Voice

Expose narrow domain tools:

```text
quest_list_pinned
quest_get_tree
quest_create
quest_update
quest_complete
quest_attach
quest_detach
quest_search
quest_propose_breakdown
```

Rules:

- MCP uses the same quest core, not raw Vikunja semantics.
- Agent-generated breakdowns begin as proposals requiring approval.
- Automatic completion records evidence and source.
- Destructive graph changes require confirmation.
- Voice pipeline converts speech to explicit MCP calls.
- "Add milk to shopping list" resolves the shopping task, creates a child, and confirms the result.

Later automatic completion could consume Git commits, calendar events, Home
Assistant state, or explicit agent evidence. Keep this outside core task truth.

## Acceptance Criteria

- Diamond graph renders correctly.
- Shared task completion updates every occurrence.
- Progress deduplicates shared descendants.
- Parent completion never changes child status.
- Deep cycle is rejected; traversal always terminates defensively.
- Duplicate attachment is idempotent.
- Pinned nested task still appears as a quest-log root.
- CLI JSON remains schema-versioned and deterministic.
- Quickshell never receives API credentials.
- Server is reachable only over the tailnet.
- An actual reminder email is delivered.
- Backup restores database and attachments.
- Android can capture and complete tasks.
- NixOS `alpha` and Home Manager desktop evaluations pass.

## Explicit Non-Goals For MVP

- Per-parent completion
- Per-parent deadlines or priority
- Manual sibling ordering
- Offline synchronization
- Native Android development
- Collaborative permissions beyond Vikunja defaults
- Automatic task decomposition
- Automatic completion
- Neovim magic buffer
- Public internet exposure

## First Implementation Slice

Deploy private Vikunja on `alpha`, run the compatibility spike, then build the
smallest `quest log/add/attach/done/pin` CLI. Stop there and use it before
investing in Quickshell.
