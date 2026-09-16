// Mirrors the TUI theme into tmux pane options so the status line can colour
// the OpenCode indicator the same way the prompt border is coloured.
//
// The agent colours here must match what the TUI actually draws. OpenCode gives
// an agent without an explicit `color` the theme colour at its index in the
// agent list, so defining any new agent renames every colour after it
// alphabetically - adding a `deep` subagent once moved plan from warning to
// primary. The agents are pinned in opencode.json to stop that; these two
// constants are the other half of that contract.
import { execFile } from "node:child_process"

const REFRESH_INTERVAL_MS = 500

function toHex(color) {
  return `#${[color.r, color.g, color.b]
    .map((channel) => Math.round(channel * 255).toString(16).padStart(2, "0"))
    .join("")}`
}

export default {
  id: "tmux-theme",
  tui: async (api) => {
    const pane = process.env.TMUX_PANE
    if (!pane) return

    let applied
    let writing = false

    const update = () => {
      if (!api.theme.ready || writing) return

      const build = toHex(api.theme.current.secondary)
      const plan = toHex(api.theme.current.warning)
      const errorColor = api.theme.current.error ? toHex(api.theme.current.error) : "red"
      const success = toHex(api.theme.current.success)
      const question = toHex(api.theme.current.info)
      const next = `${build}:${plan}:${errorColor}:${success}:${question}`
      if (next === applied) return

      writing = true
      execFile(
        "tmux",
        [
          "set-option", "-p", "-t", pane, "@opencode_build_color", build,
          ";", "set-option", "-p", "-t", pane, "@opencode_plan_color", plan,
          ";", "set-option", "-p", "-t", pane, "@opencode_error_color", errorColor,
          ";", "set-option", "-p", "-t", pane, "@opencode_success_color", success,
          ";", "set-option", "-p", "-t", pane, "@opencode_question_color", question,
        ],
        (error) => {
          writing = false
          if (!error) applied = next
        },
      )
    }

    update()
    const timer = setInterval(update, REFRESH_INTERVAL_MS)
    timer.unref?.()
    api.lifecycle.onDispose(() => clearInterval(timer))
  },
}
