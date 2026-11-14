// Every credential and network reply in this child process is synthetic.
import assert from "node:assert/strict"
import { mkdir, readFile, writeFile } from "node:fs/promises"
import path from "node:path"
import { pathToFileURL } from "node:url"
const [mode, pluginPath] = process.argv.slice(2)
assert.ok(process.env.HOME.includes("claude-auth-v2-test-"))
const file = path.join(process.env.HOME, ".claude/.credentials.json")
await mkdir(path.dirname(file), { recursive: true })
let clock = Date.now()
Date.now = () => clock
const credentials = (name, expiresAt = clock + 7200000) => ({ accessToken: `fixture-${name}`, refreshToken: `fixture-${name}-refresh`, expiresAt })
const publish = (value) => writeFile(file, JSON.stringify({ claudeAiOauth: value }))
await publish(credentials("A", ["refresh", "cli-fallback", "startup"].includes(mode) ? 1 : undefined))
let oauth = 0, resolved = 0
globalThis.fetch = async (input) => {
  const url = new URL(typeof input === "string" ? input : input.url)
  assert.equal(url.href, "https://claude.ai/v1/oauth/token")
  oauth++
  return mode === "cli-fallback"
    ? Response.json({ error: "invalid_grant" }, { status: 400 })
    : Response.json({ access_token: "fixture-renewed", refresh_token: "fixture-renewed-refresh", expires_in: 7200 })
}
const module = await import(pathToFileURL(path.join(pluginPath, "index.js")))
const hooks = {}, methods = []
const ctx = {
  integration: {
    transform: async (edit) => edit({ update() {}, method: { update: (method) => methods.push(method) } }),
    connection: {
      active: async () => ({ type: "credential", id: "fixture", method: "oauth" }),
      resolve: async () => { resolved++; throw Error("must not resolve an unused credential") },
    },
  },
  provider: { transform: async (edit) => edit({ get: () => ({ models: new Map([["claude", {}]]) }), update() {}, models: { update() {} } }), reload: async () => {} },
  session: { hook: async (name, callback) => { hooks[name] = callback } },
  event: { subscribe: async function* () { yield { type: "credential.updated", data: {} } } },
}
const cleanup = await module.default.setup(ctx)
await new Promise((resolve) => setImmediate(resolve))
for (const kind of module.IDENTITY_REQUEST_HOOKS) {
  const event = { model: { providerID: "openai" }, system: [{ type: "text", text: "GPT request" }] }
  await hooks[kind](event)
  assert.deepEqual(event.system, [{ type: "text", text: "GPT request" }])
}
await hooks["http.request"]({ model: { providerID: "openai" } })
assert.equal(resolved, 0, "startup/discovery/account events/GPT resolved Claude OAuth")
assert.equal(oauth, 0, "startup or GPT refreshed Claude")
assert.equal(methods.length, 1)
if (mode !== "startup") {
  let ticks = 0
  const timer = setInterval(() => ticks++, 10)
  let current
  try { current = await module.getCachedCredentials() } finally { clearInterval(timer) }
  if (mode === "refresh") { assert.equal(current.accessToken, "fixture-renewed"); assert.equal(oauth, 1) }
  if (mode === "cli-fallback") {
    assert.equal(current.accessToken, "fixture-cli")
    assert.ok(ticks >= 5, "CLI fallback blocked the event loop")
    assert.equal(oauth, 1)
  }
  if (mode === "switch") {
    assert.equal(current.accessToken, "fixture-A")
    await publish(credentials("B"))
    clock += 30001
    assert.equal((await module.getCachedCredentials()).accessToken, "fixture-B")
    assert.equal(oauth, 0)
  }
}
await cleanup()
console.log("PASS")
