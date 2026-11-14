# OpenCode Session Notify

Desktop notifications and distinct audio cues for OpenCode sessions that need
human attention.

## Why

Long-running agent sessions should not require constant polling. This plugin
treats notifications as a list of sessions that still require action, rather
than a log of everything OpenCode has done.

Its main principles are:

- Notify when a top-level session needs input, finishes, or fails.
- Use distinct sounds for questions, successful completion, and errors, so the
  required response is clear without looking at the screen.
- Mute all sounds, including the terminal-bell fallback, while desktop Do Not
  Disturb is enabled.
- Avoid duplicate alerts from child sessions, repeated question events, manual
  interrupts, and closely spaced lifecycle events.
- Do not show completion or error desktop notifications when the originating
  tmux pane is already focused. Audio still confirms the state change.
- Keep notifications actionable. Clicking one returns to the original tmux
  pane when possible, reconnects to an existing OpenCode session, or opens it
  in a new terminal when necessary.
- Remove notifications once their action is no longer pending. Answered
  questions close their notification, deleted sessions close related
  notifications, and tmux hooks can dismiss completion notifications when the
  pane is visited.

## Files

- `session-notify.js`: OpenCode plugin. Interprets lifecycle and question
  events, suppresses noise, generates directory-specific chimes, and launches
  the notification helper.
- `session-notify-handler.sh`: Linux helper. Owns desktop notification state
  and focuses or recreates the relevant tmux/OpenCode context when clicked.

## Requirements

Core plugin expects Linux and these commands:

- `opencode-session-notify`, installed from `session-notify-handler.sh`
- `pw-play` for audio, with terminal bell as fallback
- `tmux`
- `hyprctl` and `jq` for Hyprland window discovery and focus
- `notify-send` and `gdbus` for actionable desktop notifications
- `kitty` for opening a missing terminal context
- `flock`

OpenCode itself provides the JavaScript runtime and plugin API. No npm
dependencies are required.

## Install

1. Clone this repository somewhere stable.
2. Link `session-notify.js` into `~/.config/opencode/plugins/`.
3. Put an executable named `opencode-session-notify` on `PATH` that runs
   `session-notify-handler.sh` with all arguments unchanged.
4. Ensure requirements above are available on `PATH`.
5. Restart OpenCode; plugins are loaded only at startup.

Example wrapper:

```bash
#!/usr/bin/env bash
exec bash /absolute/path/to/opencode-session-notify/session-notify-handler.sh "$@"
```

Optional tmux hooks dismiss completion notifications when their pane becomes
active:

```tmux
set-hook -g after-select-window 'run-shell "opencode-session-notify --close-pane #{pane_id}"'
set-hook -g after-select-pane 'run-shell "opencode-session-notify --close-pane #{pane_id}"'
set-hook -g client-session-changed 'run-shell "opencode-session-notify --close-pane #{pane_id}"'
```

## Sounds

Without custom files, plugin generates short PCM WAV chimes. Tone varies by
working directory, making concurrent projects easier to distinguish.

Place optional WAV files beside `session-notify.js`:

- `session-notify-ask.wav`
- `session-notify-done.wav`
- `session-notify-error.wav`
- `session-notify.wav`, fallback custom sound for done and error states

Question sound intentionally never falls back to `session-notify.wav`; input
requests must remain audibly distinct from completion.

Before each sound, the plugin queries `quickshell ipc call notifications dnd`.
The desktop's `notifications` IPC target must return `true` when Do Not Disturb
is enabled. If Quickshell or this endpoint is unavailable, audio keeps its
normal behavior. The query times out after one second.

## Scope

Focus restoration is intentionally opinionated around tmux, Hyprland, and
Kitty. Notification-state and event-filtering logic can be reused with another
desktop by replacing `session-notify-handler.sh` while preserving its command
interface.
