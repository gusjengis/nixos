/** @jsxImportSource @opentui/solid */
//
// Status line for the Auto model router.
//
// It renders into `session_prompt_right`, the right-hand end of the prompt's
// meta row, so a routed session reads:
//
//   Build · Claude Sonnet 5 Anthropic                Auto ModelName (complex) · effort
//
// The left half is OpenCode's own model indicator. It shows the concrete model
// rather than "Auto" on purpose: the TUI re-reads the model from the last user
// message when a session comes into view, so once the router has rewritten a
// turn, the selection genuinely is that model and the router keeps routing from
// there (see auto-router.js). This half shows the tier in parentheses after the
// model name, then effort - `default` or `auto` meaning the model picks its own
// thinking budget.
//
// Decisions are read from the file the server-side plugin writes on every
// routed prompt. Polling a small local file keeps this independent of the
// server plugin's lifecycle and needs no new event types.

import fs from "node:fs"
import path from "node:path"
import { createMemo, createSignal } from "solid-js"

const POLL_INTERVAL_MS = 400
const STALE_AFTER_MS = 1000 * 60 * 60 * 12

function statusPath(options) {
  if (options?.statusFile) return options.statusFile
  const base =
    process.env.XDG_STATE_HOME ?? (process.env.HOME ? path.join(process.env.HOME, ".local", "state") : undefined)
  if (!base) return undefined
  return path.join(base, "opencode", "auto-router.json")
}

const tui = async (api, options) => {
  const file = statusPath(options)
  if (!file) return

  const [sessions, setSessions] = createSignal({})
  let lastMtime = 0

  const read = () => {
    try {
      const stat = fs.statSync(file)
      if (stat.mtimeMs === lastMtime) return
      lastMtime = stat.mtimeMs
      setSessions(JSON.parse(fs.readFileSync(file, "utf8"))?.sessions ?? {})
    } catch {
      // Missing or half-written file: keep the last good decision rather than
      // blanking the status line on a transient read.
    }
  }

  read()
  const timer = setInterval(read, POLL_INTERVAL_MS)
  timer.unref?.()
  api.lifecycle.onDispose(() => clearInterval(timer))

  api.slots.register({
    slots: {
      session_prompt_right(ctx, value) {
        const entry = createMemo(() => {
          const found = sessions()[value.session_id]
          if (!found) return undefined
          if (found.time && Date.now() - found.time > STALE_AFTER_MS) return undefined
          return found
        })

        const theme = () => ctx.theme.current

        return (
          <box flexDirection="row" gap={1}>
            {entry() ? (
              <>
                <text fg={entry().free ? theme()?.success : theme()?.textMuted}>Auto</text>
                <text fg={theme()?.text}>
                  {entry().modelName ?? entry().modelID}
                  {/* A trailing `?` means the local classifier was unreachable
                      and the keyword scorer picked this tier instead. The
                      router still routes, but it is guessing, and hiding that
                      would make a worse decision look like a better one. */}
                  <span fg={entry().graded === false ? theme()?.warning : theme()?.textMuted}>
                    {" ("}
                    {entry().tier}
                    {entry().graded === false ? "?" : ""}
                    {")"}
                  </span>
                </text>
                <text fg={theme()?.textMuted}>{"\u00b7"}</text>
                <text>
                  <span style={{ fg: theme()?.warning, bold: true }}>{entry().effort ?? "default"}</span>
                </text>
              </>
            ) : null}
          </box>
        )
      },
    },
  })
}

export default { id: "auto-router-status", tui }
