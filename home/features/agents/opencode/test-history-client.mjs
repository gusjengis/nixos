import assert from "node:assert/strict"
import { test } from "node:test"
import { mkdtemp, writeFile, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { createHistoryClient, attachHistoryState, rowStatus, runHistoryCommand } from "./history-client.mjs"

async function fixture(t) {
  const root = await mkdtemp(join(tmpdir(), "history-client-"))
  t.after(() => rm(root, { recursive: true, force: true }))
  const path = join(root, "state.json")
  const record = { owner: "owner", chat: "chat", known_revision: "revision", base_revision: "revision",
    selected_root: "native", members: { chat: "native" }, freshness: "current_as_known", availability: "local", operation: { phase: "idle" } }
  const save = async (value = record) => writeFile(path, JSON.stringify({ version: 1, generation: 1, conversations: { "owner/chat": value } }))
  await save()
  return { env: { OPENCODE_CONTEXT_STATE_FILE: path }, record, save }
}

test("unchanged local open reads authoritative verdict without spawning a helper", async (t) => {
  const { env } = await fixture(t)
  const client = createHistoryClient({ env, command: () => { throw new Error("No CLI on local open") } })
  assert.equal(await client.open({ owner: "owner", chat: "chat", nativeID: "native" }, () => {}), "native")
})

test("portable ensure must publish verified mapping; successful exit alone is insufficient", async (t) => {
  const { env, record, save } = await fixture(t)
  await save({ ...record, selected_root: null, members: {}, freshness: "outdated", availability: "portable_only" })
  let argv
  const client = createHistoryClient({ env, command: async (args) => { argv = args; return { session_id: "native" } } })
  await assert.rejects(client.open({ owner: "owner", chat: "chat", known_revision: "revision" }, () => {}), /not yet verified/)
  assert.deepEqual(argv, ["ensure", "--owner", "owner", "--chat", "chat", "--expected-revision", "revision"])
  await save()
  assert.equal(await client.open({ owner: "owner", chat: "chat" }, () => {}), "native")
  const bad = createHistoryClient({ env, command: async () => ({ session_id: "unrelated" }) })
  await assert.rejects(bad.open({ owner: "owner", chat: "chat" }, () => {}), /authoritative mapping/)
})

test("list keeps partial errors and authoritative availability, status attaches progress", async (t) => {
  const { env, record } = await fixture(t)
  const client = createHistoryClient({ env, command: async () => ({ conversations: [{ owner: "owner", chat: "chat", title: "Known", state: record }], errors: [{ owner: "other", error: "missing data" }] }) })
  const listed = await client.list()
  assert.equal(listed.summaries[0].nativeID, "native")
  assert.equal(listed.loaded, false)
  assert.match(listed.warning, /missing data/)
  const rows = attachHistoryState(listed.summaries, { conversations: { "owner/chat": { ...record, operation: { phase: "importing", completed: 1, total: 2 } } } })
  assert.equal(rowStatus(rows[0]), "importing 1/2")
})

test("command cancellation passes AbortSignal and reports cancellation, not readiness", async () => {
  const abort = new AbortController()
  let completion
  const promise = runHistoryCommand(["ensure"], { signal: abort.signal, spawn: (_cmd, args, options, cb) => {
    assert.deepEqual(args, ["ensure"])
    assert.equal(options.signal, abort.signal)
    completion = cb
  } })
  abort.abort(); completion(new Error("killed"), "", "")
  await assert.rejects(promise, /Import cancelled/)
})
