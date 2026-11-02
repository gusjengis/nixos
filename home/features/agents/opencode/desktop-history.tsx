import { createMemo, createSignal, onCleanup, onMount } from "solid-js"
import { useKeyboard } from "@opentui/solid"
import { DialogSelect } from "../ui/dialog-select"
import { useDialog } from "../ui/dialog"
import { useSync } from "../context/sync"
import { useSDK } from "../context/sdk"
import { useRoute } from "../context/route"
import { useLocal } from "../context/local"
import { desktopVisible, desktopLabel } from "../util/desktop-context"
import { DialogSessionRename } from "./dialog-session-rename"
import { createHistoryController, mergeHistory, historyStatus } from "../util/history-controller.mjs"
import { createHistoryClient, attachHistoryState, rowStatus } from "../util/history-client.mjs"

// Context-owned history has portable identities; they are never native session IDs.
export function DesktopHistory() {
  const dialog = useDialog()
  const sync = useSync()
  const sdk = useSDK()
  const route = useRoute()
  const local = useLocal()
  const client = createHistoryClient()
  const [view, setView] = createSignal<any>({ loaded: false, summaries: [] })
  const [snapshot, setSnapshot] = createSignal<any>({ conversations: {} })
  const [native, setNative] = createSignal<any[]>(sync.data.session)
  const [query, setQuery] = createSignal("")
  const [selected, setSelected] = createSignal<any>()
  const [deleting, setDeleting] = createSignal<string>()
  const [nativeError, setNativeError] = createSignal<string>()
  const [stateError, setStateError] = createSignal<string>()
  const [actionError, setActionError] = createSignal<string>()
  let disposed = false
  let routeEpoch = 0
  let refreshing = false
  let queuedRefresh = false
  const controller = createHistoryController({
    list: () => client.list(), open: (row, progress) => client.open(row, progress),
    cancel: () => client.cancel(), changed: setView,
  })
  const rows = createMemo(() => attachHistoryState(mergeHistory(
    native().filter(desktopVisible), view().summaries,
  ), snapshot()).filter((row) => row.freshness !== "deleted"))
  const status = createMemo(() => {
    const active = selected() && rows().find((row: any) => row.key === selected().key)
    const operation = view().operation?.phase === "cancelled" ? view().operation :
      active?.operation?.phase && active.operation.phase !== "idle" ? active.operation : view().operation
    return historyStatus({ ...view(), operation, error: view().error || stateError() || actionError() || nativeError() }, rows().length)
  })
  const refreshNative = async () => {
    try {
      const response = await sdk.client.session.list({ ...sync.session.query(), roots: true, limit: 100 })
      if (response.error) throw new Error("Native conversation list unavailable")
      if (!disposed) { setNative(response.data ?? []); setNativeError(undefined) }
    } catch (error) { if (!disposed) setNativeError(error instanceof Error ? error.message : String(error)) }
  }
  const refresh = async () => {
    if (refreshing) { queuedRefresh = true; return }
    refreshing = true
    try { await Promise.all([controller.refresh(), refreshNative()]) }
    finally {
      refreshing = false
      if (queuedRefresh && !disposed) { queuedRefresh = false; void refresh() }
    }
  }
  const open = async (row: any) => {
    const epoch = ++routeEpoch
    setActionError(undefined)
    setSelected(row)
    const target = await controller.select(row)
    if (!target || disposed) return
    try {
      // Imports happen in another native process, so fetch rather than waiting for bus events.
      const result = await sdk.client.session.get({ sessionID: target })
      if (result.error || !result.data) throw new Error("Imported conversation is not readable yet; retry")
      if (disposed || epoch !== routeEpoch) return
      if (!client.verified(row, target)) throw new Error("Conversation changed before opening; retry")
      route.navigate({ type: "session", sessionID: target })
      dialog.clear()
    } catch (error) { setActionError(error instanceof Error ? error.message : String(error)) }
  }
  const retry = () => {
    const row = selected() && rows().find((item: any) => item.key === selected().key)
    if (row) void open(row); else { controller.acknowledge(); void refresh() }
  }
  const cancel = () => { ++routeEpoch; void controller.cancel() }
  // alt+r/alt+x are unbound; ctrl+r is native rename and ctrl+x is the leader.
  useKeyboard((event: any) => {
    if (!(event.meta || event.option) || event.ctrl) return
    if (event.name === "r") { event.preventDefault(); event.stopPropagation(); retry() }
    if (event.name === "x") { event.preventDefault(); event.stopPropagation(); cancel() }
  })
  onMount(() => {
    dialog.setSize("large")
    void refresh()
    const stop = client.observe((value, meta) => {
      if (disposed) return
      if (!value) { setStateError(meta?.error?.message || "History state unavailable"); return }
      setStateError(undefined)
      setSnapshot(value)
      void refresh()
    })
    // Fallback discovery catches received archive heads before a state observer has indexed them.
    const timer = setInterval(() => void refresh(), 5000)
    onCleanup(() => { clearInterval(timer); stop?.() })
  })
  onCleanup(() => { disposed = true; controller.dispose(); client.cancel() })
  return <DialogSelect title="Context conversations" preserveSelection skipFilter
    onFilter={setQuery}
    options={rows().filter((row) => row.title.toLowerCase().includes(query().toLowerCase())).map((row) => ({
      title: deleting() === row.key ? "Press delete again to confirm" : row.title,
      value: row.key, category: row.session && local.session.pinned().includes(row.nativeID) ? "Pinned" : "Conversations",
      description: rowStatus(row), footer: row.source_device || (row.session ? desktopLabel(row.session) : "portable"),
    }))}
    onMove={() => setDeleting(undefined)}
    onSelect={(option) => { const row = rows().find((item) => item.key === option.value); if (row) void open(row) }}
    titleView={<text>Context conversations — {status()}</text>}
    emptyView={<text>{query() && view().loaded ? "No matching conversations" : status()}</text>}
    footer={<text>alt+r retry/refresh  alt+x cancel</text>}
    actions={[
      { command: "session.pin.toggle", title: "pin/unpin", disabled: (option) => !rows().find((row) => row.key === option?.value)?.nativeID,
        onTrigger: (option) => { const row = rows().find((row) => row.key === option.value); if (row?.nativeID) local.session.togglePin(row.nativeID) } },
      { command: "session.rename", title: "rename", disabled: (option) => !rows().find((row) => row.key === option?.value)?.nativeID,
        onTrigger: (option) => { const row = rows().find((row) => row.key === option.value); if (row?.nativeID) dialog.replace(() => <DialogSessionRename session={row.nativeID} />) } },
      { command: "session.delete", title: "delete", disabled: (option) => !rows().find((row) => row.key === option?.value)?.nativeID,
        onTrigger: async (option) => {
          if (deleting() !== option.value) { setDeleting(option.value); return }
          const row = rows().find((row) => row.key === option.value)
          if (!row?.nativeID) return
          try {
            const result = await sdk.client.session.delete({ sessionID: row.nativeID })
            if (result.error) throw new Error("Conversation deletion failed")
            setDeleting(undefined); await refresh()
          } catch (error) { setActionError(error instanceof Error ? error.message : String(error)) }
        } },
    ]} />
}
