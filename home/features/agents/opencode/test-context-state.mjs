import assert from "node:assert/strict"
import { mkdtemp, rm, writeFile } from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { test } from "node:test"
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import { assertFreshness, headToken, observeState, readState, readVerdict, verdict } from "./context-state.mjs"

const marker = { id: "owner", chat: "chat", session: "chat" }
const record = () => ({ owner: "owner", chat: "chat", generation: 1, selected_root: "native",
  members: { chat: "native" }, known_revision: "r1", base_revision: "r1",
  freshness: "current_as_known", availability: "local", operation: { phase: "idle" } })
const snapshot = (value = record()) => ({ version: 1, generation: value.generation, conversations: { "owner/chat": value } })

test("readiness separates current knowledge, availability, operations and native copy identity", () => {
  const state = snapshot()
  assert.equal(verdict(state, marker, "native").code, "ready")
  state.conversations["owner/chat"].operation = { phase: "failed" }
  assert.equal(verdict(state, marker, "native").allowed, true, "unrelated worker failure is not stale")
  assert.equal(verdict(state, marker, "old-native").code, "outdated")
  const child = { ...marker, session: "new-child" }
  assert.equal(verdict(state, child, "native-child", { rootID: "native" }).allowed, true)
  assert.equal(verdict(state, child, "old-child", { rootID: "old-root" }).allowed, false)
  for (const freshness of ["outdated", "conflict", "deleted"]) {
    state.conversations["owner/chat"].freshness = freshness
    assert.equal(verdict(state, marker, "native").code, freshness)
  }
  state.conversations["owner/chat"].freshness = "unknown"
  assert.equal(verdict(state, marker, "native").code, "unknown")
  state.conversations["owner/chat"].availability = "missing_workdir"
  assert.equal(verdict(state, marker, "native").code, "unavailable")
})

test("snapshot observer notices native atomic replacement and head changes without importing", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "context-state-observer-"))
  const file = path.join(directory, "state.json")
  const head = path.join(directory, "head.json")
  let stop
  try {
    await writeFile(head, "r1")
    const value = record()
    value.head_path = head
    value.observed_head = headToken(head)
    await writeFile(file, JSON.stringify(snapshot(value)))
    const changes = []
    stop = observeState(file, (state, detail) => changes.push({ state, detail }), { interval: 5 })
    assert.equal(changes.length, 1)
    await writeFile(head, "r2")
    assert.equal(readVerdict(file, marker, "native").code, "waiting_data")
    const deadline = Date.now() + 1000
    while (changes.length < 2 && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 5))
    assert.deepEqual(changes.at(-1).detail.changedHeads, [head])
    value.generation = 2
    value.known_revision = "r2"
    value.freshness = "outdated"
    value.observed_head = headToken(head)
    await writeFile(file, JSON.stringify(snapshot(value)))
    assert.equal(readVerdict(file, marker, "native").code, "outdated")
    await writeFile(file, "broken transfer")
    assert.equal(readVerdict(file, marker, "native").code, "state_invalid")
    assert.throws(() => readState(file))
  } finally { stop?.(); await rm(directory, { recursive: true, force: true }) }
})

test("native guard enforces hidden roots and owner boundaries with no state exemption", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "context-state-guard-"))
  try {
    const file = path.join(directory, "scope.json")
    const env = { CONTEXT_ID: "owner", OPENCODE_CONTEXT_SCOPE_FILE: file }
    const session = { id: "native", metadata: { desktop_context: marker } }
    await writeFile(file, JSON.stringify({ context_id: "owner", ids: ["owner"], hidden: [] }))
    assert.equal(assertFreshness(session, {}, env).code, "unknown")
    await writeFile(`${file}.state.json`, JSON.stringify(snapshot()))
    assert.equal(assertFreshness(session, {}, env).code, "ready")
    await writeFile(file, JSON.stringify({ context_id: "owner", ids: ["owner"], hidden: ["root"] }))
    assert.throws(() => assertFreshness(session, { rootID: "root" }, env), error => error.code === "outdated")
    assert.throws(() => assertFreshness({ ...session, metadata: { desktop_context: { ...marker, id: "sibling" } } }, {}, env),
      error => error.code === "unverified")
  } finally { await rm(directory, { recursive: true, force: true }) }
})

test("Python authoritative publication is consumed unchanged by JS gate including CAS import promotion", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "context-state-python-"))
  const file = path.join(directory, "state.json")
  const cwd = fileURLToPath(new URL("../../desktop/contexts/", import.meta.url))
  try {
    execFileSync("python3", ["-B", "-c", `
import sys
import context_chat_state as state
p=sys.argv[1]
state.publish(p, 'owner', 'chat', selected_root='native', members={'chat':'native'},
              base_revision='r1', known_revision='r1', availability='local', freshness='current_as_known')
state.observe(p, 'owner', 'chat', known_revision='r2', source_device='other-device')
`, file], { cwd })
    assert.equal(readVerdict(file, marker, "native").code, "outdated")
    assert.equal(readState(file).conversations["owner/chat"].source_device, "other-device")
    execFileSync("python3", ["-B", "-c", `
import sys
import context_chat_state as state
p=sys.argv[1]
r=state.get(p, 'owner', 'chat')
state.publish(p, 'owner', 'chat', expected_generation=r['generation'], expected_revision='r2',
              selected_root='new-native', members={'chat':'new-native'}, base_revision='r2',
              freshness='current_as_known', availability='local')
`, file], { cwd })
    assert.equal(readVerdict(file, marker, "new-native").code, "ready")
    assert.equal(readVerdict(file, marker, "native").code, "outdated")
  } finally { await rm(directory, { recursive: true, force: true }) }
})
