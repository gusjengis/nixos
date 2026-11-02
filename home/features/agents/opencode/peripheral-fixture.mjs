import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import path from "node:path"
import { setTimeout as sleep } from "node:timers/promises"
import { pathToFileURL } from "node:url"
import { connect } from "node:net"

const mode = process.argv[2]
const home = process.env.HOME
assert.ok(home.startsWith("/tmp/opencode/peripheral-test-"))
const lines = async () => (await readFile(path.join(home, "tmux-calls"), "utf8").catch(error => {
  if (error.code === "ENOENT") return ""
  throw error
})).trim().split("\n").filter(Boolean).map(JSON.parse)
const until = async (check, timeout = 3000) => {
  const end = performance.now() + timeout
  while (performance.now() < end) { if (await check()) return; await sleep(20) }
  assert.fail("peripheral operation did not recover within deadline")
}
const dead = (pid) => {
  assert.throws(() => process.kill(pid, 0), { code: "ESRCH" }, "timed-out tmux child survived")
}
let disposals = []
const api = { lifecycle: { onDispose: callback => disposals.push(callback) }, theme: { ready: true,
  current: Object.fromEntries(["secondary", "warning", "error", "success", "info"].map(key => [key, { r: 1, g: 0.5, b: 0 }])) } }
const before = performance.now()
if (mode === "status") {
  const { TmuxStatusPlugin } = await import("./plugins/tmux-status.js")
  const hooks = await TmuxStatusPlugin()
  assert.ok(performance.now() - before < 250, "tmux status initialization waited for child")
  await until(async () => (await lines()).length >= 2)
  dead((await lines())[0].pid)
  await hooks.event({ event: { type: "session.status", properties: { sessionID: "fixture", status: { type: "busy" } } } })
  await hooks.event({ event: { type: "server.instance.disposed" } })
  await sleep(100)
  const count = (await lines()).length
  await sleep(1100)
  assert.equal((await lines()).length, count, "disposed status plugin kept spawning tmux")
} else if (mode === "theme") {
  const { default: plugin } = await import("./tui-plugins/tmux-theme.js")
  await plugin.tui(api)
  assert.ok(performance.now() - before < 250, "theme initialization waited for child")
  await until(async () => (await lines()).length >= 2)
  dead((await lines())[0].pid)
  await sleep(700)
  assert.equal((await lines()).length, 2, "unchanged theme was repeatedly written")
  for (const dispose of disposals) dispose()
} else if (mode === "persistence") {
  const { default: plugin } = await import("./tui-plugins/context-persistence.js")
  Object.assign(api, { route: { current: { name: "session", params: { sessionID: "fixture-session" } } },
    state: { session: { get: () => ({ directory: home }) } } })
  await plugin.tui(api)
  assert.ok(performance.now() - before < 250, "explicit DB persistence initialization waited for tmux")
  await until(async () => (await lines()).some(call => call.args.includes("set-option")))
  dead((await lines())[0].pid)
  const selected = await new Promise((resolve, reject) => {
    const socket = connect(path.join(home, `context-chat-${process.pid}.sock`))
    let data = ""
    socket.on("data", chunk => { data += chunk })
    socket.on("end", () => resolve(JSON.parse(data)))
    socket.on("error", reject)
  })
  assert.equal(selected.database, process.env.OPENCODE_DB)
  assert.equal(selected.session_id, "fixture-session")
  for (const dispose of disposals) dispose()
  await sleep(100)
  const count = (await lines()).length
  await sleep(600)
  assert.equal((await lines()).length, count)
} else {
  const { SessionNotifyPlugin } = await import(pathToFileURL(process.env.NOTIFY_PLUGIN))
  const hooks = await SessionNotifyPlugin({ $: async () => {}, directory: home })
  const elapsed = performance.now() - before
  assert.ok(elapsed < 1000, `notification initialization blocked: ${elapsed}ms`)
  if (mode === "notify-hang") dead((await lines())[0].pid)
  await hooks.event({ event: { type: "question.asked", properties: { id: "fixture-question", sessionID: "fixture-session", questions: [] } } })
  let args
  await until(async () => {
    try { args = JSON.parse(await readFile(path.join(home, "notification"), "utf8")); return true }
    catch (error) { if (error.code === "ENOENT") return false; throw error }
  })
  assert.equal(args[5], "%fixture", "notification lost pane identity")
  assert.equal(args[6], mode === "notify-ready" ? "$fixture" : "", "tmux origin fallback incorrect")
  assert.equal(args.at(-1), "fixture-question")
}
console.log(JSON.stringify({ case: mode, calls: (await lines()).length }))
