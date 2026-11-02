import { execFile } from "node:child_process"
import { readState, readVerdict, observeState, statePath } from "./context-state.mjs"

export function runHistoryCommand(args, { signal, spawn = execFile } = {}) {
  return new Promise((resolve, reject) => {
    spawn("opencode-context-chats", args, { timeout: 120000, maxBuffer: 4 * 1024 * 1024, signal }, (error, stdout, stderr) => {
      if (error) reject(new Error(signal?.aborted ? "Import cancelled" : stderr?.trim() || error.message))
      else {
        try { resolve(stdout.trim() ? JSON.parse(stdout) : {}) }
        catch { reject(new Error("Invalid history helper response")) }
      }
    })
  })
}

export function createHistoryClient({ env = process.env, command = runHistoryCommand } = {}) {
  const path = statePath(env)
  let abort
  const snapshot = () => readState(path)
  return {
    snapshot,
    verified(row, nativeID) {
      return readVerdict(path, { id: row.owner, chat: row.chat, session: row.chat }, nativeID).allowed
    },
    observe(callback) { return observeState(path, callback, { interval: 250 }) },
    async list() {
      const result = await command(["list"])
      const summaries = (Array.isArray(result) ? result : result.summaries ?? result.conversations ?? [])
        .map((row) => ({ ...row, ...row.state, nativeID: row.state?.selected_root }))
      const errors = result.errors?.map((entry) => entry.error).join("; ")
      return { summaries, loaded: !errors, status: result.status, availability: errors ? "unavailable" : result.availability,
        warning: errors }
    },
    async open(row, progress) {
      abort?.abort()
      if (row.nativeID) {
        const marker = { id: row.owner, chat: row.chat, session: row.chat }
        const result = readVerdict(path, marker, row.nativeID)
        if (result.allowed) return row.nativeID
      }
      const current = new AbortController()
      abort = current
      const args = ["ensure", "--owner", row.owner, "--chat", row.chat]
      if (row.known_revision) args.push("--expected-revision", row.known_revision)
      progress({ phase: "importing", key: row.key })
      try {
        const result = await command(args, { signal: current.signal })
        if (current.signal.aborted) throw new Error("Import cancelled")
        const state = await snapshot()
        const record = state.conversations?.[`${row.owner}/${row.chat}`]
        const ready = record?.freshness === "current_as_known" || record?.freshness === "local_only"
        if (!ready || record.availability !== "local" || !record.selected_root) {
          throw new Error(record?.operation?.error || "Conversation is not yet verified and available")
        }
        const target = result.session_id || record.selected_root
        if (target !== record.selected_root && !Object.values(record.members ?? {}).includes(target)) {
          throw new Error("Imported session does not match authoritative mapping")
        }
        if (!readVerdict(path, { id: row.owner, chat: row.chat, session: row.chat }, target).allowed) {
          throw new Error("Conversation changed after import; refresh selection")
        }
        return target
      } finally { if (abort === current) abort = undefined }
    },
    cancel() { abort?.abort(); abort = undefined },
    refresh() { return command(["prepare"]) },
  }
}

export function attachHistoryState(rows, snapshot) {
  return rows.map((row) => {
    const record = snapshot?.conversations?.[`${row.owner}/${row.chat}`]
    return record ? { ...row, ...record, nativeID: record.selected_root ?? row.nativeID } : row
  })
}

export function rowStatus(row) {
  const operation = row.operation
  if (operation?.phase && operation.phase !== "idle") {
    const done = operation.progress?.completed ?? operation.completed
    const total = operation.progress?.total ?? operation.total
    return `${operation.phase}${total ? ` ${done ?? 0}/${total}` : ""}${operation.error ? `: ${operation.error}` : ""}`
  }
  return [row.availability ?? (row.local ? "local" : "portable_only"), row.freshness ?? "unknown"].join(" · ")
}
