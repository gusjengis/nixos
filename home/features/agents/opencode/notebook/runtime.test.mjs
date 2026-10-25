import assert from "node:assert/strict"
import test from "node:test"
import { createHooks } from "./runtime.mjs"

function fixture() {
  const schema = new Proxy(() => schema, { get: () => schema })
  const tool = definition => definition
  tool.schema = schema
  const calls = []
  const permissions = []
  let clock = 1000
  const sessions = {
    root: { metadata: { desktop_context: { id: "child-context" } } },
    delegated: { parentID: "root", metadata: { desktop_context: { id: "child-context" } } },
    unowned: {},
  }
  const client = { session: { get: async ({ path }) => ({ data: sessions[path.id] }) } }
  const run = async (id, action, request) => {
    calls.push({ id, action, request })
    return { context_id: id, vault: "/contexts/child/.context/notes", notes: [] }
  }
  const hooks = createHooks({ client, tool, run, skill: "WORKFLOW", now: () => clock })
  const context = { sessionID: "root", agent: "build", ask: async request => { permissions.push(request) } }
  const system = async (sessionID = "root", prefix = "main <env>") => {
    const output = { system: [prefix] }
    await hooks["experimental.chat.system.transform"]({ sessionID }, output)
    return output.system
  }
  return { hooks, calls, permissions, context, sessions, system, advance: ms => { clock += ms } }
}

test("automatic bootstrap uses conversation owner, reads identity only, and skips internal prompts", async () => {
  const f = fixture()
  const first = await f.system()
  assert.match(first[1], /Before replying, call notebook_read/)
  assert.match(first[1], /child-context/)
  assert.deepEqual(f.calls.map(call => call.action), ["info"])
  await f.system()
  assert.equal(f.calls.length, 1)
  assert.equal((await f.system("unowned")).length, 1)
  assert.equal((await f.system("delegated")).length, 1)
  assert.equal((await f.system("root", "You are a title generator")).length, 1)
})

test("briefing is permission checked once; later reads retrieve current notes", async () => {
  const f = fixture()
  await f.hooks.tool.notebook_read.execute({ action: "brief" }, f.context)
  assert.equal(f.permissions[0].permission, "external_directory")
  assert.equal(f.permissions[1].permission, "read")
  assert.deepEqual(f.permissions[1].patterns, ["/contexts/child/.context/notes/**"])
  assert.match((await f.system())[1], /Initial orientation is already/)
  await f.hooks.tool.notebook_read.execute({ action: "search", query: "dictation" }, f.context)
  assert.equal(f.calls.at(-1).action, "search")
})

test("read denial prevents all note reads, without suppressing normal permission errors", async () => {
  const f = fixture()
  await assert.rejects(f.hooks.tool.notebook_read.execute({ action: "read", path: "Private.md" }, {
    ...f.context, ask: async () => { throw new Error("read denied") },
  }), /read denied/)
  assert.deepEqual(f.calls.map(call => call.action), ["info"])
})

test("plan, delegation, unowned sessions and edit denial cannot write", async () => {
  const f = fixture()
  const request = { action: "create", title: "Desktop In-Progress widget" }
  await assert.rejects(f.hooks.tool.notebook_write.execute(request, { ...f.context, agent: "plan" }), /primary execution/)
  await assert.rejects(f.hooks.tool.notebook_write.execute(request, { ...f.context, sessionID: "delegated" }), /primary execution/)
  await assert.rejects(f.hooks.tool.notebook_write.execute(request, { ...f.context, sessionID: "unowned" }), /no saved context/)
  await assert.rejects(f.hooks.tool.notebook_write.execute(request, {
    ...f.context, agent: "custom-read-only", ask: async () => { throw new Error("edit denied") },
  }), /edit denied/)
  assert.ok(!f.calls.some(call => call.action === "create"))
  await f.hooks.tool.notebook_write.execute(request, f.context)
  assert.equal(f.permissions.at(-1).permission, "edit")
  assert.equal(f.calls.at(-1).id, "child-context")
  assert.equal(f.calls.at(-1).action, "create")
})

test("a resumed conversation after a gap requests fresh orientation, without background refresh", async () => {
  const f = fixture()
  await f.hooks["chat.message"]({ sessionID: "root" }, { parts: [] })
  await f.hooks.tool.notebook_read.execute({ action: "brief" }, f.context)
  f.advance(31 * 60 * 1000)
  await f.hooks["chat.message"]({ sessionID: "root" }, { parts: [] })
  assert.match((await f.system())[1], /Before replying, call notebook_read/)
})

test("ownership failures never fall back to launching/visible context", async () => {
  const f = fixture()
  const result = await f.system("missing")
  assert.match(result[1], /Do not guess a vault/)
  assert.equal(f.calls.length, 0)
  const output = { context: [] }
  await f.hooks["experimental.session.compacting"]({ sessionID: "unowned" }, output)
  assert.deepEqual(output.context, [])
})
