import assert from "node:assert/strict"
import { test } from "node:test"
import { mkdtemp, rm, stat } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { DraftStore } from "./tui-plugins/context-stale-drafts.mjs"
import { StaleController, needsBlock } from "./tui-plugins/context-stale-controller.mjs"

const identity = { owner: "owner", chat: "root", member: "child", nativeID: "old-child" }
const initial = () => ({ generation: 1, known_revision: "rev2", base_revision: "rev1",
  selected_root: "old-root", members: { child: "old-child" }, freshness: "outdated",
  availability: "portable_only", operation: { phase: "idle" } })
const imported = (record) => ({ ...record, generation: record.generation + 1,
  base_revision: record.known_revision,
  selected_root: "new-root", members: { child: "new-child", root: "new-root" },
  freshness: "current_as_known", availability: "local", operation: { phase: "idle" } })
const draft = { prompt: { input: "x", parts: [{ type: "file", url: "data:image/png;base64,AA==" },
  { type: "text", text: "full pasted text", source: { text: { start: 0, end: 1, value: "x" } } }] }, mode: "shell", cursor: 1 }

function fixture(overrides = {}) {
  let record = initial()
  const saved = [], routes = [], views = []
  let active = [], preserved = 0, ensured = 0
  const io = {
    capture: () => structuredClone(draft),
    save: async (id, value, reason) => { saved.push({ id, value: structuredClone(value), reason }); return { path: "/private/draft" } },
    check: async () => structuredClone(record),
    ensure: async () => { ensured++; record = imported(record); return { session_id: "new-child" } },
    activity: async () => [...active],
    stop: async () => { active = [] },
    preserve: async () => { preserved++; return { path: "/private/history" } },
    destinationDraft: () => undefined,
    route: async (...args) => routes.push(args),
    render: (state) => views.push(structuredClone(state)),
    ...overrides,
  }
  const controller = new StaleController(io)
  return { controller, io, saved, routes, views, get record() { return record }, set record(value) { record = value },
    set active(value) { active = value }, get preserved() { return preserved }, get ensured() { return ensured } }
}

test("stale discovery freezes immediately; deliberate open verifies and transfers complete draft", async () => {
  const f = fixture()
  const observing = f.controller.observe(identity, f.record)
  assert.equal(f.controller.state.blocked, true, "freeze precedes disk/network awaits")
  await observing
  assert.equal(f.routes.length, 0, "no silent auto-switch")
  await f.controller.act("escape")
  await f.controller.act("continue")
  assert.equal(f.controller.state.blocked, true)
  await f.controller.act("open")
  assert.equal(f.ensured, 1)
  assert.equal(f.routes[0][0], "new-child")
  assert.deepEqual(f.routes[0][1], draft)
  assert.equal(f.controller.state.blocked, false)
})

test("selected native member mismatch blocks even current-as-known record", () => {
  assert.equal(needsBlock(imported(initial()), identity), true)
  assert.equal(needsBlock(imported(initial()), { ...identity, nativeID: "new-child" }), false)
})

test("failed draft persistence blocks all routing", async () => {
  const f = fixture({ save: async () => { throw new Error("disk full") } })
  await f.controller.observe(identity, f.record)
  await f.controller.act("open")
  assert.equal(f.routes.length, 0)
  assert.match(f.controller.state.error, /disk full/)
  assert.equal(f.controller.state.blocked, true)
})

test("active family requires explicit stop confirmation; completion never auto-switches", async () => {
  const f = fixture()
  f.active = ["old-root", "running-subagent"]
  await f.controller.observe(identity, f.record)
  await f.controller.act("open")
  assert.equal(f.routes.length, 0)
  assert.equal(f.preserved, 0)
  await f.controller.act("stop")
  assert.equal(f.controller.state.phase, "confirm-stop")
  await f.controller.act("confirm-stop")
  assert.equal(f.preserved, 1)
  assert.equal(f.routes.length, 0)
  await f.controller.act("open")
  assert.equal(f.routes.length, 1)
})

test("divergence exports both histories without pretending backend conflict resolved", async () => {
  const f = fixture()
  f.record = { ...f.record, freshness: "conflict" }
  await f.controller.observe(identity, f.record)
  await f.controller.act("open")
  assert.equal(f.ensured, 0)
  await f.controller.act("preserve")
  assert.equal(f.preserved, 1)
  assert.equal(f.controller.state.phase, "conflict")
  assert.equal(f.routes.length, 0)
})

test("new revision during acknowledgement requires another deliberate acknowledgement", async () => {
  const f = fixture()
  await f.controller.observe(identity, f.record)
  f.record = { ...f.record, generation: 2, known_revision: "rev3" }
  await f.controller.act("open")
  assert.equal(f.ensured, 0)
  assert.equal(f.routes.length, 0)
  assert.match(f.controller.state.error, /changed/)
  await f.controller.act("open")
  assert.equal(f.routes.length, 1)
})

test("new update while ensure runs and double Enter never route or duplicate import", async () => {
  let release
  const f = fixture({ ensure: async () => {
    await new Promise(resolve => { release = resolve })
    f.record = { ...imported(f.record), known_revision: "rev3" }
    return { session_id: "new-child" }
  } })
  await f.controller.observe(identity, f.record)
  const opening = f.controller.act("open")
  while (!release) await new Promise(resolve => setImmediate(resolve))
  await f.controller.act("open")
  release()
  await opening
  assert.equal(f.routes.length, 0)
  assert.equal(f.controller.state.blocked, true)
  assert.match(f.controller.state.error, /Newer update/)
})

test("incomplete or failed import and wrong member never route", async () => {
  for (const behavior of ["failed", "incomplete", "wrong-member"]) {
    const f = fixture({ ensure: async () => {
      if (behavior === "failed") throw new Error("incomplete transfer")
      if (behavior === "wrong-member") f.record = imported(f.record)
      return { session_id: "unverified" }
    } })
    await f.controller.observe(identity, f.record)
    await f.controller.act("open")
    assert.equal(f.routes.length, 0, behavior)
    assert.equal(f.controller.state.blocked, true)
  }
})

test("revision/mapping race immediately before route and newly active work block handoff", async () => {
  for (const race of ["mapping", "work"]) {
    const f = fixture()
    let checks = 0, activities = 0
    f.io.check = async () => {
      checks++
      if (race === "mapping" && checks === 4) return { ...f.record, generation: 9, members: { child: "other-copy" } }
      return structuredClone(f.record)
    }
    f.io.activity = async () => (++activities >= 3 && race === "work" ? ["subagent"] : [])
    await f.controller.observe(identity, f.record)
    await f.controller.act("open")
    assert.equal(f.routes.length, 0, race)
    assert.equal(f.controller.state.blocked, true)
  }
})

test("destination draft collision preserves both and needs explicit draft decision", async () => {
  const destination = { prompt: { input: "latest draft", parts: [] }, cursor: 4 }
  const f = fixture({ destinationDraft: async () => destination })
  await f.controller.observe(identity, f.record)
  await f.controller.act("open")
  assert.equal(f.controller.state.phase, "draft-conflict")
  assert.equal(f.saved.length, 2)
  assert.equal(f.routes.length, 0)
  await f.controller.chooseDraft("latest")
  assert.deepEqual(f.routes[0][1], destination)
})

test("late rejected dispatch preserved separately from newer visible typing", async () => {
  const f = fixture()
  await f.controller.observe(identity, f.record)
  const rejected = { prompt: { input: "sent before update", parts: [] } }
  await f.controller.observe(identity, f.record, rejected)
  assert.equal(f.saved.length, 2)
  assert.deepEqual(f.saved[1].value, rejected)
  assert.deepEqual(f.controller.draft, draft)
})

test("missing child requires explicit root decision", async () => {
  const f = fixture({ ensure: async () => {
    f.record = { ...imported(f.record), members: { root: "new-root" } }
    return { session_id: "new-root" }
  } })
  await f.controller.observe(identity, f.record)
  await f.controller.act("open")
  assert.equal(f.routes.length, 0)
  assert.match(f.controller.state.error, /Selected child missing/)
  f.controller.chooseRoot()
  await f.controller.act("open")
  assert.equal(f.routes[0][0], "new-root")
})

test("draft files durable/private and loadable across store recreation", async () => {
  const directory = await mkdtemp(join(tmpdir(), "stale-drafts-"))
  try {
    const saved = await new DraftStore(directory).save(identity, draft)
    const recovered = await new DraftStore(directory).load(saved.id)
    assert.deepEqual(recovered.draft, draft)
    assert.deepEqual(recovered.identity, identity)
    assert.deepEqual((await new DraftStore(directory).latest(identity)).draft, draft)
    assert.equal(await new DraftStore(directory).latest({ ...identity, nativeID: "unrelated" }), undefined)
    assert.equal((await stat(saved.path)).mode & 0o777, 0o600)
    await assert.rejects(new DraftStore(directory).load("../escape"), /Invalid/)
  } finally { await rm(directory, { recursive: true, force: true }) }
})
