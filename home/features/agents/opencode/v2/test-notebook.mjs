import assert from "node:assert/strict"
import test from "node:test"
import { setupNotebook } from "./plugins/notebook/index.js"

async function fixture() {
  const hooks = {}, definitions = {}, permissions = [], calls = []
  let denied
  const sessions = {
    root: { location: { directory: "/project" }, metadata: { desktop_context: { id: "owner" } } },
    child: { parentID: "root", location: { directory: "/project" }, metadata: { desktop_context: { id: "owner" } } },
    unowned: { location: { directory: "/project" } },
  }
  let aborted = false
  const ctx = {
    session: {
      get: async ({ sessionID }) => { if (!sessions[sessionID]) throw Error("missing"); return sessions[sessionID] },
      hook: async (name, callback) => { hooks[name] = callback },
    },
    permission: { assert: async (input) => { permissions.push(input); if (input.action === denied) throw Error("denied") } },
    tool: { transform: async (edit) => edit({ add: (tool) => { definitions[tool.name] = tool } }) },
    event: { subscribe: async function* ({ signal }) {
      await new Promise((resolve) => signal.addEventListener("abort", () => { aborted = true; resolve() }, { once: true }))
    } },
  }
  const cleanup = await setupNotebook(ctx, {
    skill: "NOTEBOOK WORKFLOW",
    run: async (owner, action, payload) => {
      calls.push({ owner, action, payload })
      if (action === "read") return { path: "Outcome.md", status: "In-Progress" }
      return { context_id: owner, vault: "/contexts/owner/notes", notes: [] }
    },
  })
  const context = { sessionID: "root", agent: "build", messageID: "msg_test", id: "call_test" }
  const system = async (sessionID = "root") => {
    const event = { sessionID, system: [{ type: "text", text: "V2 primary request" }] }
    await hooks.context(event)
    return event.system.map((part) => part.text).join("\n")
  }
  return { hooks, definitions, permissions, calls, context, system, deny: (action) => { denied = action },
    async close() { await cleanup(); assert.equal(aborted, true) } }
}

test("V2 notebook tools register native schemas and retain owner-aware bootstrap", async () => {
  const f = await fixture()
  try {
    assert.deepEqual(f.definitions.notebook_read.input.required, ["action"])
    assert.equal(f.definitions.notebook_read.input.properties.limit.minimum, 1)
    assert.match(await f.system(), /NOTEBOOK WORKFLOW.*Before replying/s)
    assert.doesNotMatch(await f.system("unowned"), /NOTEBOOK WORKFLOW/)
    assert.doesNotMatch(await f.system("child"), /NOTEBOOK WORKFLOW/)
    assert.match(await f.system("missing"), /Do not guess a vault/)
    assert.ok(f.calls.every((call) => call.owner === "owner"))
  } finally { await f.close() }
})

test("V2 notebook permissions use session agent, tool source, and normal read/edit actions", async () => {
  const f = await fixture()
  try {
    await f.definitions.notebook_read.execute({ action: "brief" }, f.context)
    assert.deepEqual(f.permissions.map((entry) => entry.action), ["external_directory", "read"])
    assert.deepEqual(f.permissions[1], {
      sessionID: "root", agent: "build", action: "read", resources: ["/contexts/owner/notes/**"],
      save: ["/contexts/owner/notes/**"], metadata: { context_id: "owner", action: "brief" },
      source: { type: "tool", messageID: "msg_test", id: "call_test" },
    })
    assert.match(await f.system(), /Initial orientation is already/)
    f.deny("edit")
    await assert.rejects(f.definitions.notebook_write.execute({ action: "create", title: "Denied" }, f.context), /denied/)
    assert.ok(!f.calls.some((call) => call.action === "create"))
  } finally { await f.close() }
})

test("V2 Plan, delegated and unowned sessions cannot write; closeout survives compaction", async () => {
  const f = await fixture()
  try {
    const write = (context) => f.definitions.notebook_write.execute({ action: "create" }, context)
    await assert.rejects(write({ ...f.context, agent: "plan" }), /primary execution/)
    await assert.rejects(write({ ...f.context, sessionID: "child" }), /primary execution/)
    await assert.rejects(write({ ...f.context, sessionID: "unowned" }), /no saved context/)
    await f.definitions.notebook_read.execute({ action: "read", path: "Outcome.md" }, f.context)
    assert.match(await f.system(), /Notebook closeout.*Outcome.md/)
    const event = { sessionID: "root", system: [] }
    await f.hooks.compaction(event)
    assert.match(event.system.map((part) => part.text).join("\n"), /Outcome.md/)
    assert.equal(f.calls.filter((call) => ["create", "update"].includes(call.action)).length, 0)
  } finally { await f.close() }
})
