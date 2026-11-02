// UI-only state. Freshness and availability are supplied by the library backend.
export const historyKey = (owner, chat) => JSON.stringify([owner, chat])

export function mergeHistory(native, summaries, hidden = []) {
  const rows = new Map()
  const excluded = new Set(hidden)
  for (const session of native) {
    if (session.parentID || excluded.has(session.id)) continue
    const marker = session.metadata?.desktop_context
    const key = marker ? historyKey(marker.id, marker.chat) : session.id
    rows.set(key, { key, owner: marker?.id, chat: marker?.chat, title: session.title,
      updated: session.time?.updated ?? 0, nativeID: session.id, session, local: true })
  }
  for (const summary of summaries) {
    const key = historyKey(summary.owner, summary.chat)
    if (summary.deleted) { rows.delete(key); continue }
    const local = rows.get(key)
    rows.set(key, { ...local, ...summary, key,
      title: summary.title || local?.title || `Conversation ${summary.chat}`,
      updated: summary.updated ?? local?.updated ?? 0,
      nativeID: summary.nativeID ?? local?.nativeID,
      local: Boolean(summary.nativeID ?? local?.nativeID) })
  }
  return [...rows.values()].sort((a, b) => b.updated - a.updated || a.key.localeCompare(b.key))
}

export function historyStatus(state, count) {
  if (state.error || state.listError) return `Failed: ${state.error || state.listError}`
  if (state.warning) return `Unavailable: ${state.warning}`
  if (state.operation) {
    const op = state.operation
    const progress = op.total > 0 ? ` ${op.completed ?? 0}/${op.total}` : ""
    return `${op.phase || "Waiting"}${progress}${op.message ? ` — ${op.message}` : ""}`
  }
  if (!state.loaded) return "Loading portable history; local conversations remain available"
  if (state.availability === "unavailable") return "Portable history unavailable; showing known conversations"
  if (state.status === "conflict") return "Conflict — both histories retained"
  if (state.status === "updating" || state.status === "waiting") return `${state.status} — showing known conversations`
  return count ? "Current as known — remote devices may have newer changes" : "No conversations"
}

/** @param {{list: () => Promise<any>, open: (row: any, progress: (operation: any) => void) => Promise<any>, cancel: (operation?: any) => any, changed?: (state: any) => void}} options */
export function createHistoryController({ list, open, cancel, changed = () => {} }) {
  let state = { loaded: false, summaries: [], error: undefined, operation: undefined }
  let refreshID = 0
  let selectionID = 0
  let disposed = false
  const update = (next) => { if (!disposed) { state = { ...state, ...next }; changed(state) } }
  return {
    get state() { return state },
    async refresh() {
      const id = ++refreshID
      try {
        const result = await list()
        if (id === refreshID) update({ ...result, loaded: result.loaded ?? true, listError: undefined })
      } catch (error) {
        if (id === refreshID) update({ listError: error.message })
      }
    },
    async select(row) {
      const id = ++selectionID
      update({ operation: { phase: "Waiting", key: row.key }, error: undefined })
      try {
        const nativeID = await open(row, (operation) => {
          if (id === selectionID) update({ operation })
        })
        if (disposed || id !== selectionID) return
        update({ operation: undefined })
        return nativeID
      } catch (error) {
        if (id === selectionID) update({ error: error.message, operation: undefined })
      }
    },
    async cancel() {
      ++selectionID
      const operation = state.operation
      update({ operation: { phase: "cancelled", message: "Selected request cancelled" } })
      try { await cancel(operation) } catch (error) { update({ error: error.message }) }
    },
    acknowledge() { if (state.operation?.phase === "cancelled" || state.error) update({ operation: undefined, error: undefined }) },
    dispose() { disposed = true; ++refreshID; ++selectionID },
  }
}
