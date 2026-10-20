// Selection belongs to this TUI, never to server bus activity. Socket replies
// read the route getter immediately, so managed close need not wait for polling.
import { execFile } from "node:child_process"
import { createServer } from "node:net"
import { chmodSync, readFileSync, unlinkSync } from "node:fs"
import { join } from "node:path"

export default {
  id: "context-persistence",
  tui: async (api) => {
    const runtime = process.env.XDG_RUNTIME_DIR
    if (!runtime) return
    // Resolve channel/custom database location once at TUI startup. Periodic
    // capture can then fingerprint SQLite read-only without starting native CLI.
    const database = process.env.OPENCODE_DB ?? await new Promise((resolve) => {
      execFile("opencode", ["db", "path"], { timeout: 10000 }, (error, stdout) => {
        resolve(error ? null : stdout.trim())
      })
    })
    const socket = join(runtime, `context-chat-${process.pid}.sock`)
    const pane = process.env.TMUX_PANE
    // TMUX's last two fields are numeric; socket names may contain commas.
    const tmux = process.env.TMUX?.replace(/,\d+,\d+$/, "")
    let applied
    let writing = false
    let disposed = false
    let listening = false
    let panePID = null
    const startTicks = (pid) => {
      try { return readFileSync(`/proc/${pid}/stat`, "utf8").split(") ").at(-1).split(" ")[19] }
      catch { return null }
    }
    const processStart = startTicks(process.pid)
    const selection = () => {
      const route = api.route.current
      const id = route.name === "session" ? route.params?.sessionID : null
      const session = id ? api.state.session.get(id) : undefined
      return {
        pid: process.pid,
        session_id: id ?? null,
        directory: session?.directory ?? api.state.path?.directory ?? process.cwd(),
        parent_id: session?.parentID ?? null,
        database,
        pane_id: pane ?? null,
        tmux_socket: tmux ?? null,
        pid_start_ticks: processStart,
        pane_pid: panePID,
        pane_start_ticks: panePID ? startTicks(panePID) : null,
      }
    }
    const publish = () => {
      if (!pane || !tmux || writing || disposed) return
      const value = JSON.stringify(selection())
      if (value === applied) return
      writing = true
      // pane_pid lets readers verify that pid is still a descendant of this
      // pane's process, rather than trusting options left by a dead TUI.
      execFile("tmux", ["-S", tmux, "display-message", "-p", "-t", pane, "#{pane_pid}"], (error, pid) => {
        if (error || disposed) { writing = false; return }
        panePID = Number(pid.trim())
        const metadata = JSON.stringify(selection())
        execFile("tmux", ["-S", tmux,
          "set-option", "-p", "-t", pane, "@persistence-chat", metadata,
          ";", "set-option", "-p", "-t", pane, "@persistence-chat-socket", socket,
        ], (error) => { writing = false; if (!error) applied = value })
      })
    }
    // PID-specific path: never unlink an existing live endpoint.
    const server = createServer((connection) => {
      connection.on("error", () => {})
      connection.end(`${JSON.stringify(selection())}\n`)
    })
    server.on("error", () => {})
    server.listen(socket, () => { listening = true; chmodSync(socket, 0o600); publish() })
    server.unref()
    const timer = setInterval(publish, 200)
    timer.unref?.()
    api.lifecycle.onDispose(() => {
      disposed = true
      clearInterval(timer)
      server.close()
      if (listening) { try { unlinkSync(socket) } catch {} }
      // Leave PID metadata for readers to reject, rather than clearing options
      // that a replacement TUI may already have published.
    })
  },
}
