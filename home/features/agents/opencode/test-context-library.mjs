import assert from "node:assert/strict"
import childProcess from "node:child_process"
import { syncBuiltinESMExports } from "node:module"
import { mkdtemp, rm, writeFile } from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { test } from "node:test"
import { ContextLibraryPlugin } from "./plugins/context-library.js"
import { headToken } from "./context-state.mjs"

test("fresh and existing sends never await discovery; incoming updates revoke eligibility including children", async (t) => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "context-library-test-"))
  const previous = { ...process.env }
  const callbacks = []
  let killed = 0
  t.mock.method(childProcess, "execFile", (_command, args, options, callback) => {
    assert.deepEqual(args, ["prepare"])
    assert.equal(options.timeout, 10000)
    callbacks.push(callback)
    return { kill: () => { killed++ } }
  })
  syncBuiltinESMExports()
  let hooks
  try {
    process.env.CONTEXT_ID = "fixture-owner"
    process.env.OPENCODE_CONTEXT_SCOPE_FILE = path.join(directory, "scope.json")
    delete process.env.OPENCODE_CONTEXT_STATE_FILE
    delete process.env.OPENCODE_CONTEXT_HELPER
    const scope = (hidden = []) => writeFile(process.env.OPENCODE_CONTEXT_SCOPE_FILE,
      JSON.stringify({ context_id: "fixture-owner", ids: ["fixture-owner"], hidden }))
    await scope()
    const marker = { id: "fixture-owner", chat: "root", session: "root" }
    const sessions = {
      root: { id: "root", metadata: { desktop_context: marker } },
      child: { id: "child", parentID: "root", metadata: { desktop_context: { ...marker, session: "child" } } },
    }
    const client = {
      tui: { showToast: async () => {} },
      session: { get: async ({ path: { id } }) => ({ data: sessions[id] }) },
    }
    hooks = await ContextLibraryPlugin({ client })
    assert.equal(callbacks.length, 1)
    const quickSend = (sessionID) => Promise.race([
      hooks["chat.message"]({ sessionID }),
      new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error("Send waited for discovery")), 100); timer.unref() }),
    ])
    await quickSend("root")
    await quickSend("child")
    const head = path.join(directory, "current.json")
    await writeFile(head, "head r1")
    const record = { owner: marker.id, chat: "root", generation: 1, selected_root: "root",
      members: { root: "root", child: "child" }, known_revision: "r1", base_revision: "r1",
      freshness: "current_as_known", availability: "local", operation: { phase: "idle" },
      head_path: head, observed_head: headToken(head) }
    const publish = () => writeFile(`${process.env.OPENCODE_CONTEXT_SCOPE_FILE}.state.json`,
      JSON.stringify({ version: 1, generation: record.generation, conversations: { "fixture-owner/root": record } }))
    await publish()
    await quickSend("root")
    assert.equal(callbacks.length, 1, "unchanged foreground send launches no helper")
    // Catch the head/observer race synchronously, before new state is published.
    await writeFile(head, "head r2")
    await assert.rejects(quickSend("root"), /update is arriving/)
    record.generation++
    record.known_revision = "r2"
    record.observed_head = headToken(head)
    record.freshness = "outdated"
    await publish()
    await assert.rejects(quickSend("root"), /Newer portable conversation/)
    await assert.rejects(quickSend("child"), /Newer portable conversation/)
    await assert.rejects(hooks["command.execute.before"]({ sessionID: "root" }), /Newer portable conversation/)
    // Import completion changes selected root; old native copies remain blocked.
    record.generation++
    record.selected_root = "replacement"
    record.members = { root: "replacement", child: "replacement-child" }
    record.base_revision = "r2"
    record.freshness = "current_as_known"
    await publish()
    await assert.rejects(quickSend("child"), /Newer portable conversation/)
    callbacks.shift()(new Error("discovery failed"), "", "incomplete transfer")
    sessions.fresh = { id: "fresh", metadata: { desktop_context: { ...marker, chat: "fresh", session: "fresh" } } }
    await quickSend("fresh")
    await scope(["root"])
    await assert.rejects(quickSend("child"), /Newer portable conversation/)
    await scope()
    await writeFile(process.env.OPENCODE_CONTEXT_SCOPE_FILE, JSON.stringify({ context_id: "wrong" }))
    await assert.rejects(quickSend("fresh"), /state is invalid/)
  } finally {
    await hooks?.event({ event: { type: "server.instance.disposed" } })
    process.env = previous
    t.mock.restoreAll()
    syncBuiltinESMExports()
    await rm(directory, { recursive: true, force: true })
  }
})

test("disposal terminates pending discovery and removes its exit listener", async (t) => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "context-library-stop-"))
  const previous = { ...process.env }
  let killed = 0
  t.mock.method(childProcess, "execFile", () => ({ kill: () => killed++ }))
  syncBuiltinESMExports()
  try {
    process.env.CONTEXT_ID = "owner"
    process.env.OPENCODE_CONTEXT_SCOPE_FILE = path.join(directory, "scope")
    delete process.env.OPENCODE_CONTEXT_HELPER
    delete process.env.OPENCODE_CONTEXT_STATE_FILE
    const before = process.listenerCount("exit")
    const hooks = await ContextLibraryPlugin({ client: { tui: { showToast: async () => {} } } })
    assert.equal(process.listenerCount("exit"), before + 1)
    await hooks.event({ event: { type: "server.instance.disposed" } })
    assert.equal(killed, 1)
    assert.equal(process.listenerCount("exit"), before)
  } finally {
    process.env = previous
    t.mock.restoreAll()
    syncBuiltinESMExports()
    await rm(directory, { recursive: true, force: true })
  }
})
