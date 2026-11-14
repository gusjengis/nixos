import { execFile } from "node:child_process"
import { agentThemeColor } from "../../agent-colors.mjs"

export function startTheme(ctx, { pane = process.env.TMUX_PANE, execute = execFile } = {}) {
  if (!pane) return () => {}
  let applied, writing = false, disposed = false
  const hex = (color) => typeof color === "string" ? color : `#${[color.r, color.g, color.b]
    .map((channel) => Math.round(channel * 255).toString(16).padStart(2, "0")).join("")}`
  const agentColor = (id) => {
    const agents = (ctx.data.location.agent.list(ctx.location) ?? []).filter((agent) => !agent.hidden)
    const index = agents.findIndex((agent) => agent.id === id)
    const scale = ctx.theme.categorical[Math.max(index, 0) % ctx.theme.categorical.length]
    const color = agents[index]?.color
    return color ? color.startsWith("#") ? color : agentThemeColor(ctx.theme, color) ?? scale[200] : scale[200]
  }
  const update = () => {
    if (disposed || writing) return
    const colors = [agentColor("build"), agentColor("plan"), ctx.theme.text.feedback.error.base,
      ctx.theme.text.feedback.success.base, ctx.theme.text.feedback.info.base].map(hex)
    const value = colors.join(":")
    if (value === applied) return
    const names = ["build", "plan", "error", "success", "question"]
    const args = colors.flatMap((color, index) => [
      ...(index ? [";"] : []), "set-option", "-p", "-t", pane, `@opencode_${names[index]}_color`, color,
    ])
    writing = true
    execute("tmux", args, { timeout: 500, killSignal: "SIGKILL" }, (error) => {
      writing = false
      if (!error && !disposed) applied = value
    })
  }
  update()
  const timer = setInterval(update, 500)
  timer.unref?.()
  return () => { disposed = true; clearInterval(timer) }
}

export default { id: "desktop.tmux-theme", setup: (ctx) => startTheme(ctx) }
