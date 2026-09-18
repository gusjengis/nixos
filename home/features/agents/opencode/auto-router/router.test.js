import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import test from "node:test"
import { AutoRouterPlugin } from "./auto-router.js"
import { continuationKind } from "./classify.js"

const A = "anthropic/claude-sonnet-5"
const O = "openai/gpt-5.6-sol"

async function fixture(t, overrides = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "router-test-"))
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }))
  const statusFile = path.join(directory, "state.json")
  const client = {
    app: { log: async () => {} },
    config: { providers: async () => ({ data: { providers: [
      { id: "anthropic", models: { "claude-sonnet-5": { variants: { low: {}, high: {}, xhigh: {} } }, "claude-opus-5": { variants: { xhigh: {} } }, "claude-haiku-4-5": {} } },
      { id: "openai", models: { "gpt-5.6-sol": { variants: { medium: {}, high: {} } }, "gpt-5.6-sol-fast": { variants: { low: {} } }, "gpt-5.6-luna-fast": {} } },
    ] } }) },
  }
  const hooks = await AutoRouterPlugin({ client }, {
    statusFile, log: false, usage: { enabled: false }, classifier: { enabled: false }, ...overrides,
  })
  let selected = { providerID: "auto", modelID: "auto" }
  const send = async (ask, files = [], model = selected) => {
    const output = { message: { sessionID: "test", model }, parts: [{ type: "text", text: ask }, ...files] }
    await hooks["chat.message"]({}, output)
    selected = output.message.model
    return { output, state: JSON.parse(fs.readFileSync(statusFile, "utf8")).sessions.test }
  }
  return { send, hooks, statusFile }
}

test("acknowledgements require whole-message match", () => {
  for (const ask of ["thanks, fix the auth bug", "great, delete the database", "nice, now review this"]) {
    assert.equal(continuationKind(ask), undefined)
  }
  for (const ask of ["thanks", "thanks, that worked", "got it!", "that worked"]) {
    assert.equal(continuationKind(ask), "acknowledgement")
  }
})

test("hard task retains working tier, model and effort through thanks and shorter work", async (t) => {
  const f = await fixture(t)
  const first = await f.send("!deep investigate")
  for (const ask of ["thanks", "fix this typo", "yes"]) {
    const next = await f.send(ask)
    assert.equal(next.state.tier, "reasoning")
    assert.deepEqual(next.output.message.model, first.output.message.model)
  }
  assert.equal((await f.send("!fast fix this typo")).state.tier, "simple")
})

test("attachment-only and acknowledgement with attachment cannot bypass medium floor", async (t) => {
  const f = await fixture(t)
  const file = { type: "file", mime: "image/png", url: "file:///fake.png" }
  assert.equal((await f.send("", [file])).state.tier, "medium")
  assert.equal((await f.send("thanks", [file])).state.tier, "medium")
})

test("failed-work retry escalates above prior tier", async (t) => {
  const f = await fixture(t)
  await f.send("!medium work")
  assert.equal((await f.send("try again")).state.tier, "complex")
  assert.equal((await f.send("still broken")).state.tier, "reasoning")
  await f.send("!trivial hello")
  assert.equal((await f.send("retry", [{ type: "file" }])).state.tier, "medium")
})

function usageOptions(openai, anthropic) {
  return {
    enabled: true,
    read: () => ({ providers: [
      { id: "openai-personal", saved: true, fetched_at: Date.now() / 1000, windows: [{ used: openai }] },
      { id: "anthropic", fetched_at: Date.now() / 1000, windows: [{ used: anthropic }] },
    ] }),
    run: async () => ({ ok: true, active: "personal", saved: ["personal"] }),
  }
}

test("quota exhaustion searches higher pools before giving up", async (t) => {
  const f = await fixture(t, { tiers: { trivial: [O], simple: [O], medium: [A] }, usage: usageOptions(100, 10) })
  const result = await f.send("!trivial hello")
  assert.equal(result.state.tier, "medium")
  assert.equal(result.state.providerID, "anthropic")
})

test("all subscriptions exhausted gives controlled error, not pseudo endpoint", async (t) => {
  const f = await fixture(t, { usage: usageOptions(100, 100) })
  await assert.rejects(f.send("!deep work"), /Auto router: no usable model/)
})

test("blocked fallback stays blocked", async (t) => {
  const f = await fixture(t, { tiers: { reasoning: [A] }, fallback: A, blocked: [A] })
  await assert.rejects(f.send("!deep work"), /no usable model/)
})

test("near-quality model remains sticky after headroom changes", async (t) => {
  let openai = 80
  const usage = usageOptions(0, 10)
  const read = usage.read
  usage.read = () => {
    const data = read()
    data.providers[0].windows[0].used = openai
    return data
  }
  const f = await fixture(t, { usage })
  const first = await f.send("!complex work")
  assert.equal(first.state.providerID, "anthropic")
  openai = 0
  assert.equal((await f.send("yes")).state.providerID, "anthropic")
})

test("a failed turn is not marked proven when session becomes idle", async (t) => {
  const f = await fixture(t)
  await f.send("!complex work")
  await f.hooks.event({ event: { type: "session.error", properties: { sessionID: "test", error: { name: "APIError", data: { message: "network timeout" } } } } })
  await f.hooks.event({ event: { type: "session.idle", properties: { sessionID: "test" } } })
  assert.deepEqual(JSON.parse(fs.readFileSync(f.statusFile, "utf8")).health ?? {}, {})
})

test("routing waits for account activation and immediately uses new headroom", async (t) => {
  let activated = false
  const usage = usageOptions(100, 100)
  const read = usage.read
  usage.read = () => ({ providers: [...read().providers,
    { id: "openai-business", saved: true, fetched_at: Date.now() / 1000, windows: [{ used: 20 }] },
  ] })
  usage.run = async (_bin, args) => {
    if (args[0] === "select") {
      await new Promise((resolve) => setTimeout(resolve, 5))
      activated = true
      return { ok: true, active: "business", switched: true }
    }
    return { ok: true, active: "personal", saved: ["personal", "business"] }
  }
  const f = await fixture(t, { usage })
  const result = await f.send("!complex work")
  assert.equal(activated, true)
  assert.equal(result.state.providerID, "openai")
  assert.equal(result.state.account, "business")
  assert.equal(result.state.headroom, 80)
})
