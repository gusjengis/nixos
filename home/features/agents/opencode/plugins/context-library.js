import { execFile } from "node:child_process"
import { observeState, statePath } from "../context-state.mjs"

// Discover portable history in the background; never gate local submissions.
export const ContextLibraryPlugin = async ({ client }) => {
  const owner = process.env.CONTEXT_ID
  const scopeFile = process.env.OPENCODE_CONTEXT_SCOPE_FILE
  if (!owner || !scopeFile || process.env.OPENCODE_CONTEXT_HELPER) return {}
  const toast = (message, variant = "info") => {
    void client.tui.showToast({ body: { title: "Context chat library", message, variant } }).catch(() => {})
  }
  let child
  let disposed = false
  let running = false
  let lastFailure
  const prepare = () => {
    if (disposed || running) return
    running = true
    child = execFile("opencode-context-chats", ["prepare"], { timeout: 10000, maxBuffer: 256 * 1024 }, (error, _stdout, stderr) => {
      running = false
      child = undefined
      const failure = error ? (stderr.trim() || error.message) : undefined
      if (failure && failure !== lastFailure && !disposed) toast("Portable history discovery failed: " + failure, "error")
      lastFailure = failure
    })
  }
  prepare()
  const stopObserving = observeState(statePath(), (_snapshot, detail) => {
    if (detail.changedHeads?.length) prepare()
  })
  // Also discover entirely new conversations/owners, including an empty library
  // that has no head_path records yet. Helpers are coalesced within this server.
  const timer = setInterval(prepare, 5000)
  timer.unref?.()
  const stop = () => {
    if (disposed) return
    disposed = true
    clearInterval(timer)
    stopObserving()
    child?.kill("SIGTERM")
    child = undefined
    process.removeListener("exit", stop)
  }
  process.once("exit", stop)
  return {
    event: async ({ event }) => {
      if (event.type === "server.instance.disposed") stop()
    },
  }
}
