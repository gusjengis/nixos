import assert from "node:assert/strict"
import { test } from "node:test"
import { createHistoryController, historyKey, historyStatus, mergeHistory } from "./history-controller.mjs"

const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const native = { id: "local", title: "Local", time: { updated: 1 }, metadata: { desktop_context: { id: "owner", chat: "chat" } } }

test("merge uses portable identity, retains native mapping, removes tombstones and hidden copies", () => {
  const rows = mergeHistory([native, { ...native, id: "hidden" }], [{ owner: "owner", chat: "chat", title: "Portable", updated: 2 }], ["hidden"])
  assert.equal(rows.length, 1)
  assert.equal(rows[0].nativeID, "local")
  assert.equal(rows[0].title, "Portable")
  assert.equal(rows[0].key, historyKey("owner", "chat"))
  assert.deepEqual(mergeHistory([native], [{ owner: "owner", chat: "chat", deleted: true }]), [])
})

test("loading, unavailable, error and successfully empty history are distinct", () => {
  assert.match(historyStatus({ loaded: false }, 0), /Loading/)
  assert.match(historyStatus({ loaded: true, availability: "unavailable" }, 0), /unavailable/)
  assert.match(historyStatus({ loaded: true, error: "offline" }, 0), /Failed: offline/)
  assert.equal(historyStatus({ loaded: true }, 0), "No conversations")
  assert.match(historyStatus({ operation: { phase: "Importing", completed: 2, total: 4 } }, 0), /Importing 2\/4/)
})

test("late listing cannot overwrite a newer refresh; failure preserves summaries", async () => {
  const first = deferred(), second = deferred()
  let calls = 0
  const ctl = createHistoryController({ list: () => ++calls === 1 ? first.promise : second.promise })
  const a = ctl.refresh(), b = ctl.refresh()
  second.resolve({ summaries: [{ title: "new" }] }); await b
  first.resolve({ summaries: [{ title: "old" }] }); await a
  assert.equal(ctl.state.summaries[0].title, "new")
  const bad = createHistoryController({ list: async () => { throw new Error("missing index") } })
  await bad.refresh()
  assert.equal(bad.state.loaded, false)
  assert.equal(bad.state.listError, "missing index")
})

test("cancel and disposal prevent late import from navigating; retry can succeed", async () => {
  const work = deferred()
  let calls = 0, cancelled
  const ctl = createHistoryController({ open: async (_row, progress) => {
    progress({ id: "operation", phase: "Importing" })
    if (++calls === 1) return work.promise
    return "committed"
  }, cancel: async (op) => { cancelled = op.id } })
  const opening = ctl.select({ key: "one" })
  await ctl.cancel()
  work.resolve("late")
  assert.equal(await opening, undefined)
  assert.equal(cancelled, "operation")
  assert.equal(ctl.state.operation.phase, "cancelled")
  assert.equal(await ctl.select({ key: "one" }), "committed")
  ctl.dispose()
  assert.equal(await ctl.select({ key: "two" }), undefined)
})

test("background refresh cannot erase selected import failure", async () => {
  const ctl = createHistoryController({ list: async () => ({ summaries: [{ title: "retained" }] }),
    open: async () => { throw new Error("archive missing") }, cancel: () => {} })
  await ctl.select({ key: "one" })
  await ctl.refresh()
  assert.match(historyStatus(ctl.state, 1), /archive missing/)
  assert.equal(ctl.state.summaries[0].title, "retained")
})
