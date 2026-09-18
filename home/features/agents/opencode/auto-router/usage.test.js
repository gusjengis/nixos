import assert from "node:assert/strict"
import test from "node:test"
import { createUsage } from "./usage.js"

const NOW = 2_000_000_000_000
const entry = (id, used, extra = {}) => ({
  id, saved: true, available: true, fetched_at: NOW / 1000,
  windows: [{ used, reset: NOW / 1000 + 3600 }], ...extra,
})

function fixture({ active = "personal", personal = 100, business = 99, stale = false, missing = false, failSelect = false } = {}) {
  let identity = active
  let time = NOW
  const calls = []
  const data = { providers: [entry("anthropic", 20), entry("openai-personal", personal), entry("openai-business", business)] }
  const usage = createUsage({
    now: () => time,
    read: () => missing ? undefined : structuredClone({ providers: data.providers.map((p) => stale ? { ...p, fetched_at: 1 } : p) }),
    run: async (bin, args) => {
      calls.push([bin, ...args])
      if (bin === "quickshell-ai-usage") return structuredClone(data)
      if (args[0] === "select") {
        assert.equal(args[2], identity)
        if (failSelect) return undefined
        identity = args[1]
        return { ok: true, active: identity, switched: true }
      }
      return { ok: true, active: identity, saved: ["personal", "business"] }
    },
  })
  return { usage, calls, data, setActive: (value) => { identity = value }, advance: (ms) => { time += ms } }
}

test("exhausted personal switches to business with only 1% remaining", async () => {
  const { usage, calls } = fixture()
  assert.equal(await usage.prepare(), "business")
  assert.equal(usage.headroom("openai"), 1)
  assert.deepEqual(calls.at(-1), ["quickshell-ai-account", "select", "business", "personal"])
})

test("business exhaustion switches in reverse", async () => {
  const { usage } = fixture({ active: "business", personal: 80, business: 100 })
  assert.equal(await usage.prepare(), "personal")
  assert.equal(usage.headroom("openai"), 20)
})

test("both exhausted and merely low accounts never switch", async () => {
  for (const personal of [99, 100]) {
    const { usage, calls } = fixture({ personal, business: 100 })
    await usage.prepare()
    assert.equal(calls.some((c) => c[1] === "select"), false)
    assert.equal(usage.headroom("openai"), 100 - personal)
  }
})

test("authoritative identity wins over stale cache active flags and follows widget", async () => {
  const f = fixture({ personal: 20, business: 40 })
  f.data.providers[1].active = true
  f.data.providers[2].active = true
  await f.usage.prepare()
  assert.equal(f.usage.headroom("openai"), 80)
  f.setActive("business")
  await f.usage.prepare()
  assert.equal(f.usage.headroom("openai"), 60)
})

test("missing and stale cache are refreshed before selection", async () => {
  for (const options of [{ missing: true }, { stale: true }]) {
    const { usage, calls } = fixture(options)
    assert.equal(await usage.prepare(), "business")
    assert.equal(calls[1][0], "quickshell-ai-usage")
  }
})

test("failed selection confirms identity and never assumes alternate activated", async () => {
  const { usage, calls } = fixture({ failSelect: true })
  assert.equal(await usage.prepare(), undefined)
  assert.equal(usage.activeOpenAIProfile(), "personal")
  assert.equal(usage.headroom("openai"), 0)
  assert.equal(calls.at(-1)[1], "status")
})

test("simultaneous prepares coalesce into one switch", async () => {
  const { usage, calls } = fixture()
  await Promise.all([usage.prepare(), usage.prepare(), usage.prepare()])
  assert.equal(calls.filter((c) => c[1] === "select").length, 1)
})

test("stale, unavailable, missing or reset usage never establishes alternate headroom", async () => {
  for (const extra of [
    { stale: true }, { available: false }, { windows: [] },
    { windows: [{ used: 0, reset: NOW / 1000 - 1 }] },
    { windows: [{ used: null }] },
  ]) {
    const f = fixture()
    Object.assign(f.data.providers[2], extra)
    await f.usage.prepare()
    assert.equal(f.calls.some((c) => c[1] === "select"), false)
  }
})

test("quota error invalidation requests refresh on next turn, not mid-turn", async () => {
  const f = fixture({ personal: 30, business: 40 })
  await f.usage.prepare()
  f.usage.invalidate()
  assert.equal(f.calls.some((c) => c[0] === "quickshell-ai-usage"), false)
  await f.usage.prepare()
  assert.equal(f.calls.filter((c) => c[0] === "quickshell-ai-usage").length, 1)
  f.usage.invalidate()
  await f.usage.prepare()
  assert.equal(f.calls.filter((c) => c[0] === "quickshell-ai-usage").length, 2)
})

test("persistent missing usage is throttled rather than polled every turn", async () => {
  const f = fixture()
  f.data.providers[2].windows = []
  await f.usage.prepare()
  await f.usage.prepare()
  assert.equal(f.calls.filter((c) => c[0] === "quickshell-ai-usage").length, 1)
  f.advance(60_001)
  await f.usage.prepare()
  assert.equal(f.calls.filter((c) => c[0] === "quickshell-ai-usage").length, 2)
})

test("unexpired exhausted weekly window still blocks after short window resets", async () => {
  const f = fixture()
  f.data.providers[1].windows = [{ used: 100, reset: NOW / 1000 - 1 }, { used: 100, reset: NOW / 1000 + 3600 }]
  assert.equal(await f.usage.prepare(), "business")
})

test("failed refresh is not forgotten by rereading last-good cache on next turn", async () => {
  const data = { providers: [entry("anthropic", 20), entry("openai-personal", 100), entry("openai-business", 20)] }
  let selects = 0
  const usage = createUsage({
    now: () => NOW,
    read: () => structuredClone(data),
    run: async (bin, args) => {
      if (bin === "quickshell-ai-usage") return { providers: data.providers.map((p) => p.id === "openai-business" ? { ...p, stale: true } : p) }
      if (args[0] === "select") selects++
      return { ok: true, active: "personal", saved: ["personal", "business"] }
    },
  })
  usage.invalidate()
  await usage.prepare()
  await usage.prepare()
  assert.equal(selects, 0)
})
