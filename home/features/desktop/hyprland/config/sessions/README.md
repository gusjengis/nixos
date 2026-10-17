# Live Hyprland Sessions

An ephemeral, tmux-like session layer for the Lua-enabled Hyprland fork used by
this repository. This is **not** a plugin for stock Hyprland's hyprlang config.
The module has no Nix, Quickshell, or personal application dependencies.

Each session owns numbered workspace slots 1-10 **per monitor**, plus named
session-local special workspaces shared between that session's monitors.
Special workspaces can instead be global, shared by all sessions. Switching sessions
switches all enabled, non-mirrored monitors together. Windows keep running on
their original workspaces; they are not serialized, closed, or rearranged.

## Try It Here

- `Super+Z`: open session picker.
- Type a name with no matching session and press Enter to create and switch.
- `Ctrl+N`: create using the field text, even when search has matches.
- Up/Down and Enter: select and switch.
- F2 or Ctrl+R: rename selected session; Enter saves.
- Ctrl+D: request closing selected session; Y confirms, N or Escape cancels.
- Escape: close picker.
- `Super+Ctrl+grave`: toggle previous session.
- Existing numbered and application scratchpad bindings remain unchanged.

The bar shows the active session name; click it to open the picker. Existing
windows are adopted into `default` on first load without moving them. Application
commands and bindings live in `../workspaces.lua`, not in this module.

Terminal scratchpads create a distinct default tmux session for each desktop
session. Existing tmux sessions and initially adopted terminals are untouched.
Project search may explicitly switch the tmux client within the active desktop
session's terminal, as before.

Closing a session requests normal application window closure, not process kills.
Global scratchpads are left alone; session-local pinned windows close normally.
A populated session and its remaining window are focused so you can handle save dialogs, including
Kitty's in-window close confirmation on a previously hidden workspace. It stays listed as `Closing...` until all
its local windows exit. Enter returns to it, and Ctrl+D can retry closure after
a canceled dialog. Once finished, the prior surviving session is selected.
`default` is an ordinary session and can be closed while named sessions remain.
Closing the final session creates one fresh, empty `default` with a new ID;
closing several sessions at once does not create a fallback before the last
one exits. Terminal tmux sessions may remain detached, just as when closing a
terminal normally.
New save dialogs and delayed application windows are never auto-closed. A late
window belonging to a closed session is adopted into the active session rather
than reopening the closed one. Ctrl+D can explicitly retry closure while a
session is still waiting for its application windows to exit.

Qobuz (`Super+Shift+Q`) and Music Assistant (`Super+M`) are global. Every session
reaches the same player workspace. Other application scratchpads remain local.

## Embed the Backend

Place this directory on Hyprland's Lua module path, then configure it once:

```lua
local sessions = require("sessions")
sessions.setup({
    specials = {
        terminal = function(id, compositor_signature)
            return "kitty tmux new-session -A -s desktop-"
                .. compositor_signature .. "-" .. id
        end,
        browser = "chromium --new-window",
        music = "music-player",
    },
    global_specials = { music = true },
    launch_matches = {
        browser = { class = "^(chromium|chromium-browser|Chromium)$" },
    },
})

hl.bind("SUPER + 1", function() sessions.select_workspace(1) end)
hl.bind("SUPER + T", function() sessions.toggle_special("terminal") end)
```

`specials` maps roles to shell commands or functions returning shell commands.
Functions receive session ID and compositor instance signature, not session name.
Names can change; IDs remain stable throughout the compositor lifetime.

`global_specials` is an optional role-to-boolean map. Omitted roles are
session-local. A global scratchpad has one workspace across all sessions and
monitors; focusing it never changes the active session. Its bar icon and shortcut
are available in every session. If visible when switching sessions, it remains
visible on that monitor, taking precedence over the incoming session's local
scratchpad. Hiding it does not cause another session to reopen it later.

Scope changes apply on config reload. Promoting a role reuses its existing
populated workspace, consolidating other copies into it without closing windows.
Changing it back to local assigns that shared workspace to the currently active
session. No player is relaunched merely because its scope changes.

Optional `launch_matches` supplies ordinary Hyprland window-rule match tables.
For programs that forward launch requests to an existing process, a temporary
static rule routes the next matching window to its destination without taking
focus. The rule is disabled on mapping or after ten seconds. Launches of the
same matched role are serialized across sessions to avoid conflicting rules.
Unexpired pending launches survive config reloads without spawning twice.
An unrelated matching window opened during that short interval can also be
routed there; use narrow matches. This is not application-instance isolation.

### API

Execute operations directly in Lua, or through `hyprctl eval`:

```sh
hyprctl eval "require('sessions').create('Job Hunt')"
hyprctl eval "require('sessions').switch('s1')"
hyprctl eval "require('sessions').previous()"
```

The matching fork's `hyprctl eval` returns `ok` on success, not Lua return values.
Check stdout as well as process exit status for errors. Read the JSON snapshot
for state.

| Function | Behavior |
| --- | --- |
| `create(name)` | Create, switch, return stable ID to Lua caller |
| `switch(id)` | Switch all outputs; remember prior session |
| `rename(id, name)` | Rename without renaming workspaces |
| `close(id)` | Gracefully close local windows; remove session once they exit |
| `kill(id)` | Alias for `close(id)` for existing clients |
| `previous()` | Toggle previous session, if any |
| `select_workspace(slot, monitor?)` | Show numbered slot; close visible special |
| `move_window(slot, monitor?)` | Move focused window to active session's slot |
| `cycle(offset)` | Cycle active monitor's slots, wrapping 1-10 |
| `toggle_special(role, monitor?)` | Toggle role; lazily launch when empty |
| `show_special(role, monitor?)` | Idempotently show role; lazily launch when empty |
| `special_name(role)` | Return role's local or global raw `special:...` address |
| `launch_special(role, command, expected_workspace?)` | Launch silently, without showing; reject stale expected address |
| `focus_window(address)` | Switch owning session, then focus window; use `address:0x...` |
| `state()` | Return frontend snapshot as a Lua table |

Omitted monitor means focused monitor. The backend handles registry, ownership,
navigation, and reload state. Frontends should not keep a second registry.

### Runtime Protocol

Files are under `$XDG_RUNTIME_DIR/hyprland-sessions-$HYPRLAND_INSTANCE_SIGNATURE`:

- `.json`: atomically replaced, read-only frontend snapshot.
- `.lua`: private Lua data for surviving configuration reloads. Loaded with an
  empty Lua environment; treat it as trusted same-user runtime state, not input
  from another machine or synchronization service.

JSON shape:

```json
{
  "active": "s2",
  "previous": "s1",
  "sessions": [{"id": "s1", "name": "default", "closing": false, "window_count": 2}, {"id": "s2", "name": "Job Hunt", "closing": true, "window_count": 1}],
  "workspaces": {"DP-1": ["slot-1-address", "slot-2-address"]},
  "specials": {"terminal": "special:session-s2-terminal", "music": "special:music"}
}
```

Real `workspaces` arrays contain ten raw addresses. Prefix regular named
addresses with `name:` when passing to native dispatchers; special addresses
already include `special:`. Prefer backend operations instead of doing this
yourself. Workspaces have an immutable address and a separate display name;
renaming a display name does not change ownership.
Native `monitor:set_special_workspace()` instead accepts a bare name without
`special:`. The backend handles this conversion for showing and restoring.

New compositor instance gets a new registry. These files are **not** durable
context storage and should not be synced. Old instance files may remain until
the runtime directory is cleared, but are never read by a new instance.

## Boundaries

- No reboot restoration, notes, root directories, or allowlists.
- This organizes normal navigation, not a security boundary. Raw compositor
  commands and third-party workspace selectors can still reach hidden sessions.
  Explicitly focusing an owned window switches all outputs to its session.
- Built-in three-finger navigation is replaced with session-aware slot cycling.
  Gesture animation is not reproduced. Activation requests no longer steal focus.
- Pinned windows stay with their owning session. They follow workspace changes
  inside that session, hide when switching away, and return pinned when switching
  back. Pin intent survives configuration reloads. Explicitly global scratchpads
  remain shared; pinning a window out of a scratchpad makes it a regular session
  window, matching the compositor's native behavior.
  Output teardown can temporarily leave a window without a monitor even after its
  workspace reconnects. Native pin toggles are deferred for those windows, then
  retried after workspace activation reattaches them; they do not block switching.
- Single-instance applications (for example some chat and notes clients) may not
  provide independent windows. When their scratchpads are session-local, a second
  launch may leave a scratchpad empty. The backend does not steal another
  session's window or silently create separate application profiles.
- Chromium uses separate windows, not separate profiles or cookies. Opening a
  URL in an existing window relies on Chromium's focused-window routing.
- Only existing 1-10 numbered/monitor-slot workspaces and configured scratchpad
  names are initially adopted. Arbitrary custom workspaces are left untouched.

Switch failures attempt to restore the previous view and publish the resulting
state. Failed creation releases its name when the new session is still empty and
inactive. With no enabled outputs, activation reports a retryable error rather
than reserving an invisible session; monitor reconnection triggers reconciliation.

## Tests

From repository root, with Lua available:

```sh
XDG_RUNTIME_DIR=/tmp/opencode HYPRLAND_INSTANCE_SIGNATURE=test-sessions \
  nix shell nixpkgs#lua --command lua \
  home/features/desktop/hyprland/config/sessions/test.lua
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover \
  -s home/features/desktop/quickshell -p test_session_search.py
```

Backend tests mock compositor operations across two monitors, existing windows,
local/global scratchpads, scope changes, launches, navigation, reload, external
focus, session-local pin suspension/restoration, orphaned pin recovery, monitor
disconnect/reconnect, failed activation rollback, and safe session closure.
No desktop applications are launched by tests.
