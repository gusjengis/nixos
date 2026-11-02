// Child process only. All credentials and endpoints are synthetic.
import assert from "node:assert/strict"
import { mkdir, readFile, stat, writeFile } from "node:fs/promises"
import path from "node:path"
import { pathToFileURL } from "node:url"

const mode = process.argv[2]
const home = process.env.HOME
assert.ok(home.startsWith(path.join(process.env.OPENCODE_AUTH_TEST_ROOT, "claude-auth-test-")))
const file = path.join(home, ".claude", ".credentials.json")
const authFile = path.join(home, ".local/share/opencode/auth.json")
const metadata = { organization: "fixture-only", mcpOAuth: { unrelated: true } }
let clock = Date.now()
Date.now = () => clock
const creds = (name, expiresAt = clock + 7_200_000) => ({ accessToken: `fixture-${name}`,
  refreshToken: `fixture-${name}-refresh`, expiresAt })
const publish = async (value) => writeFile(file, JSON.stringify({ ...metadata, claudeAiOauth: value }), { mode: 0o600 })
await publish(creds("A", ["expired", "idle-expired", "cli-fallback", "refresh-switch", "transient", "terminal", "single-flight"].includes(mode) ? 1 : undefined))
await mkdir(path.dirname(authFile), { recursive: true })
const openai = { type: "oauth", access: "fixture-openai-unchanged", refresh: "fixture-openai-refresh" }
await writeFile(authFile, JSON.stringify({ openai }), { mode: 0o600 })

// Capture just the proactive timer. No five-minute sleeps or global fake timers
// that could accidentally make subprocess and HTTP deadlines ineffective.
const timers = []
const realInterval = globalThis.setInterval
globalThis.setInterval = (callback, ms, ...args) => {
  if (ms === 300_000) { timers.push(callback); return { unref() {} } }
  return realInterval(callback, ms, ...args)
}
let oauth = 0, gpt = 0
const refreshTokens = []
const tokens = []
let refreshStarted, finishRefresh
const started = new Promise(resolve => { refreshStarted = resolve })
const release = new Promise(resolve => { finishRefresh = resolve })
globalThis.fetch = async (input, init) => {
  const url = new URL(typeof input === "string" ? input : input.url ?? input)
  if (url.href === "https://claude.ai/v1/oauth/token") {
    oauth++
    refreshTokens.push(new URLSearchParams(init.body).get("refresh_token"))
    if (mode === "refresh-switch" || mode === "single-flight") { refreshStarted(); await release }
    if (mode === "cli-fallback" || mode === "terminal") return Response.json({ error: "invalid_grant" }, { status: 400 })
    if (mode === "transient") return Response.json({ error: "temporarily_unavailable" }, { status: 429, headers: { "retry-after": "60" } })
    return Response.json({ access_token: "fixture-renewed", refresh_token: "fixture-renewed-refresh", expires_in: 7200 })
  }
  if (url.href === "https://fixture.invalid/gpt") { gpt++; return new Response("OK") }
  assert.equal(url.origin, "https://api.anthropic.com", "unexpected network destination")
  assert.equal(url.pathname, "/v1/messages")
  const token = new Headers(init.headers).get("authorization")
  tokens.push(token)
  if ((mode === "rotate-401" || mode === "rotate-429") && tokens.length === 1) {
    await publish(creds("B"))
    return Response.json({ error: { type: "fixture_error" } }, { status: mode === "rotate-401" ? 401 : 429, headers: { "retry-after": "3600" } })
  }
  return new Response("data: [DONE]\n\n", { headers: { "content-type": "text/event-stream" } })
}
const entry = pathToFileURL(process.env.CLAUDE_AUTH_PLUGIN)
const { default: plugin } = await import(entry.href)
const before = performance.now()
const hooks = await plugin()
const startupMs = performance.now() - before
assert.ok(startupMs < 500, `initialization blocked: ${startupMs}ms`)
const loaded = await hooks.auth.loader(async () => ({ type: "oauth" }), { models: {} })
assert.equal(oauth, 0, "initialization/provider discovery refreshed Claude")
assert.equal(timers.length, 1)
const system = { system: ["fixture system"] }
await hooks["experimental.chat.system.transform"]({ model: { providerID: "openai" } }, system)
assert.deepEqual(system.system, ["fixture system"])
await fetch("https://fixture.invalid/gpt")
await timers[0]()
assert.equal(oauth, 0, "GPT-only idle timer refreshed Claude")
const request = () => loaded.fetch("https://api.anthropic.com/v1/messages", { method: "POST",
  body: JSON.stringify({ model: "claude-sonnet-5", messages: [] }) })
const cliCalls = async () => (await readFile(path.join(home, "cli-calls"), "utf8").catch(error => {
  if (error.code === "ENOENT") return ""
  throw error
})).trim().split("\n").filter(Boolean).length

if (mode === "idle-expired") {
  clock += 3_600_000
  for (let i = 0; i < 4; i++) { await fetch("https://fixture.invalid/gpt"); await timers[0]() }
  assert.equal(oauth, 0)
  assert.equal(tokens.length, 0)
} else if (mode === "expiry") {
  await request()
  clock += 7_200_001
  await request()
  assert.deepEqual(tokens, ["Bearer fixture-A", "Bearer fixture-renewed"])
  assert.equal(oauth, 1)
} else if (mode === "rotate") {
  await request()
  await publish(creds("B"))
  await request() // Existing 30s cache semantics are preserved.
  clock += 30_001
  await request()
  assert.deepEqual(tokens, ["Bearer fixture-A", "Bearer fixture-A", "Bearer fixture-B"])
  assert.equal(oauth, 0)
} else if (mode === "refresh-switch") {
  const pending = request()
  await started
  await publish(creds("B"))
  finishRefresh()
  await pending
  assert.equal(JSON.parse(await readFile(file, "utf8")).claudeAiOauth.accessToken, "fixture-B", "refresh overwrote external account switch")
  clock += 30_001
  await request()
  assert.equal(tokens.at(-1), "Bearer fixture-B")
} else if (mode === "single-flight") {
  const first = request()
  await started
  const second = request()
  finishRefresh()
  await Promise.all([first, second])
  assert.equal(oauth, 1)
  assert.deepEqual(tokens, ["Bearer fixture-renewed", "Bearer fixture-renewed"])
} else if (mode === "authorize") {
  await request()
  await publish(creds("B"))
  const method = hooks.auth.methods[0]
  assert.deepEqual(method.prompts, []) // Linux file source has one account slot.
  const result = await method.authorize({ account: "file" })
  assert.equal((await result.callback()).access, "fixture-B")
  assert.equal(await readFile(path.join(home, ".local/share/opencode/claude-account-source.txt"), "utf8"), "file")
  await request()
  assert.deepEqual(tokens, ["Bearer fixture-A", "Bearer fixture-B"])
  const restarted = await plugin()
  const reloaded = await restarted.auth.loader(async () => ({ type: "oauth" }), { models: {} })
  await reloaded.fetch("https://api.anthropic.com/v1/messages", { method: "POST" })
  assert.equal(tokens.at(-1), "Bearer fixture-B")
} else if (mode === "proactive") {
  await request()
  await publish(creds("B", clock + 1_800_000))
  await timers[0]()
  assert.equal(oauth, 1)
  assert.deepEqual(refreshTokens, ["fixture-B-refresh"], "proactive refresh used pre-switch account")
  assert.equal(JSON.parse(await readFile(authFile, "utf8")).anthropic.access, "fixture-renewed")
} else if (mode === "transient" || mode === "terminal") {
  if (mode === "transient") {
    assert.equal((await request()).status, 429)
    assert.equal(oauth, 1, "cooldown must suppress repeated OAuth calls")
  } else {
    await assert.rejects(request, /credentials are unavailable or expired/)
    assert.equal(await cliCalls(), 2)
    assert.equal(oauth, 1, "terminal failure repeated authentication in the same request")
  }
  const count = oauth
  await fetch("https://fixture.invalid/gpt")
  assert.equal(oauth, count, "GPT dispatch must not invoke Claude authentication")
  assert.equal(tokens.length, 0)
} else {
  let ticks = 0
  const tick = realInterval(() => ticks++, 10)
  try { await request() } finally { clearInterval(tick) }
  if (mode === "cli-fallback") {
    assert.ok(ticks > 5, "CLI fallback blocked event loop")
    assert.equal(await cliCalls(), 1)
  }
  if (mode === "rotate-401" || mode === "rotate-429") {
    assert.deepEqual(tokens, ["Bearer fixture-A", "Bearer fixture-B"])
    assert.equal(oauth, 0)
  } else {
    assert.deepEqual(tokens, [`Bearer fixture-${mode === "valid" ? "A" : mode === "cli-fallback" ? "cli" : "renewed"}`])
    assert.equal(oauth, mode === "valid" ? 0 : 1)
  }
}
if (!["cli-fallback", "terminal"].includes(mode)) assert.equal(await cliCalls(), 0)
const disk = JSON.parse(await readFile(file, "utf8"))
assert.deepEqual(disk.organization, metadata.organization)
assert.deepEqual(disk.mcpOAuth, metadata.mcpOAuth)
assert.deepEqual(JSON.parse(await readFile(authFile, "utf8")).openai, openai)
assert.equal((await stat(authFile)).mode & 0o777, 0o600)
assert.ok(gpt > 0)
console.log(JSON.stringify({ case: mode, startupMs, oauth, requests: tokens.length, gpt }))
