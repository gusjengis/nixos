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
      const next = `${build}:${plan}:${errorColor}`
      if (next === applied) return

      writing = true
      execFile(
        "tmux",
        [
          "set-option", "-p", "-t", pane, "@opencode_build_color", build,
          ";", "set-option", "-p", "-t", pane, "@opencode_plan_color", plan,
          ";", "set-option", "-p", "-t", pane, "@opencode_error_color", errorColor,
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
