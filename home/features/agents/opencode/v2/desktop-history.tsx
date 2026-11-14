import { createMemo, createSignal, onCleanup, onMount } from "solid-js"
import { useKeyboard } from "@opentui/solid"
import { DialogSelect } from "../ui/dialog-select"
import { useDialog } from "../ui/dialog"
import { useData } from "../context/data"
import { useClient } from "../context/client"
import { useRoute } from "../context/route"
import { useLocal } from "../context/local"
import { desktopVisible, desktopLabel } from "../util/desktop-context"
import { DialogSessionRename } from "./dialog-session-rename"
import { createHistoryController, mergeHistory, historyStatus } from "../util/history-controller.mjs"
import { createHistoryClient, attachHistoryState, rowStatus } from "../util/history-client.mjs"
import { withTimestampedFallback } from "@opencode/util/session-title-fallback"

export function DesktopHistory() {
  const dialog = useDialog()
  const data = useData()
  const sdk = useClient().api
  const route = useRoute()
  const local = useLocal()
  const client = createHistoryClient()
  const [view, setView] = createSignal<any>({ loaded: false, summaries: [] })
  const [snapshot, setSnapshot] = createSignal<any>({ conversations: {} })
  const [native, setNative] = createSignal<any[]>(data.session.list())
  const [query, setQuery] = createSignal("")
  const [selected, setSelected] = createSignal<any>()
  const [deleting, setDeleting] = createSignal<string>()
  const [nativeError, setNativeError] = createSignal<string>()
  const [stateError, setStateError] = createSignal<string>()
  const [actionError, setActionError] = createSignal<string>()
  let disposed = false, routeEpoch = 0, refreshing = false, queuedRefresh = false
  const controller = createHistoryController({
    list: () => client.list(), open: (row, progress) => client.open(row, progress),
    cancel: () => client.cancel(), changed: setView,
  })
  const rows = createMemo(() => attachHistoryState(mergeHistory(
    native().filter(desktopVisible).map((info) => ({ ...info, title: withTimestampedFallback(info) })), view().summaries,
  ), snapshot()).filter((row) => row.freshness !== "deleted"))
  const status = createMemo(() => {
    const active = selected() && rows().find((row: any) => row.key === selected().key)
    const operation = view().operation?.phase === "cancelled" ? view().operation :
      active?.operation?.phase && active.operation.phase !== "idle" ? active.operation : view().operation
    return historyStatus({ ...view(), operation, error: view().error || stateError() || actionError() || nativeError() }, rows().length)
  })
  const refreshNative = async () => {
    try {
      const response = await sdk.session.list({ parentID: null, archived: false, limit: 100 })
      if (!disposed) { setNative(response.data); setNativeError(undefined) }
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
      await data.session.sync(target)
      if (!data.session.get(target)) throw new Error("Imported conversation is not readable yet; retry")
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
        onTrigger: (option) => { const row = rows().find((item) => item.key === option.value); if (row?.nativeID) local.session.togglePin(row.nativeID) } },
      { command: "session.rename", title: "rename", disabled: (option) => !rows().find((row) => row.key === option?.value)?.nativeID,
        onTrigger: (option) => { const row = rows().find((item) => item.key === option.value); if (row?.nativeID) dialog.replace(() => <DialogSessionRename sessionID={row.nativeID} currentTitle={row.title} />) } },
      { command: "session.delete", title: "delete", disabled: (option) => !rows().find((row) => row.key === option?.value)?.nativeID,
        onTrigger: async (option) => {
          if (deleting() !== option.value) { setDeleting(option.value); return }
          const row = rows().find((item) => item.key === option.value)
          if (!row?.nativeID) return
          try {
            await sdk.session.remove({ sessionID: row.nativeID })
            setDeleting(undefined); await refresh()
          } catch (error) { setActionError(error instanceof Error ? error.message : String(error)) }
        } },
    ]} />
}
