import { test, expect, mock } from "bun:test"
import { chmodSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { headToken } from "./context-state.mjs"

// Real plugin + real native bridge + real OC5 state adapter + real draft store.
// Only terminal rendering, OpenCode server SDK and OC2 CLI are fixtures.
mock.module("solid-js", () => ({
  createSignal: (initial: any) => {
    let value = initial
    return [() => value, (next: any) => { value = next }]
  },
  Show: () => undefined,
  onCleanup: () => {},
}))
mock.module("@opentui/solid", () => ({ useTerminalDimensions: () => () => ({ width: 80, height: 24 }) }))
mock.module("@opentui/solid/jsx-runtime", () => ({ jsx: () => ({}), jsxs: () => ({}), Fragment: {} }))
mock.module("@opentui/solid/jsx-dev-runtime", () => ({ jsxDEV: () => ({}), Fragment: {} }))
const { desktopStale: host } = await import("./context-stale-host")
const plugin = (await import("./tui-plugins/context-stale.tsx")).default

const until = async (condition: () => boolean, message: string) => {
  for (let i = 0; i < 400; i++) {
    if (condition()) return
    await new Promise((resolve) => setTimeout(resolve, 10))
  }
  throw new Error(`Timed out: ${message}`)
}

test("superseded chat blocks, ignores dismissal, imports verified latest, transfers draft", async () => {
  const directory = mkdtempSync(join(tmpdir(), "oc6-plugin-"))
  const previous = { ...process.env }
  const disposers: (() => any)[] = []
  try {
    const scope = join(directory, "scope.json")
    const state = `${scope}.state.json`
    writeFileSync(scope, JSON.stringify({ context_id: "owner", ids: ["owner"], hidden: [], labels: {} }))
    const head = join(directory, "current.json")
    writeFileSync(head, "local checkpoint 1")
    const record = { owner: "owner", chat: "root", known_revision: "rev2", base_revision: "rev1",
      selected_root: "old-root", members: { root: "old-root" }, freshness: "outdated", availability: "portable_only",
      source_device: "omega", observed_head: null, head_path: null, operation: { phase: "idle" }, generation: 2 }
    const publish = (value: any) => writeFileSync(state, JSON.stringify({ version: 1,
      generation: value.generation, conversations: { "owner/root": value } }))
    const local = { ...record, known_revision: "rev1", freshness: "current_as_known", availability: "local",
      head_path: head, observed_head: headToken(head) }
    publish(local)
    writeFileSync(head, "local checkpoint 2 with new archive bytes")
    const bin = join(directory, "bin")
    const calls = join(directory, "calls")
    require("node:fs").mkdirSync(bin)
    writeFileSync(join(bin, "opencode-context-chats"), `#!${process.execPath}
const fs = require("node:fs")
const [command, ...args] = process.argv.slice(2)
fs.appendFileSync(${JSON.stringify(calls)}, JSON.stringify([command, ...args]) + "\\n")
const snapshot = JSON.parse(fs.readFileSync(${JSON.stringify(state)}, "utf8"))
let record = snapshot.conversations["owner/root"]
if (command === "ensure") {
  if (args[args.indexOf("--expected-revision") + 1] !== record.known_revision) { console.error("revision changed"); process.exit(3) }
  snapshot.generation++
  record = { ...record, base_revision: record.known_revision, selected_root: "new-root", members: { root: "new-root" },
    freshness: "current_as_known", availability: "local", generation: snapshot.generation }
  snapshot.conversations["owner/root"] = record
  fs.writeFileSync(${JSON.stringify(state)}, JSON.stringify(snapshot))
  record = { ...record, session_id: "new-root", directory: "/work" }
}
process.stdout.write(JSON.stringify(record))
`)
    chmodSync(join(bin, "opencode-context-chats"), 0o755)
    Object.assign(process.env, { CONTEXT_ID: "owner", OPENCODE_CONTEXT_SCOPE_FILE: scope,
      XDG_STATE_HOME: join(directory, "state"), PATH: `${bin}:${process.env.PATH}` })
    delete process.env.OPENCODE_CONTEXT_HELPER
    delete process.env.OPENCODE_CONTEXT_STATE_FILE

    const draft = { prompt: { input: "[Image 1] keep this", parts: [{ type: "file", mime: "image/png", url: "data:image/png;base64,AA==" }] },
      mode: "normal", cursor: 9 }
    let restored: any
    const unbindOld = host.bindPrompt({ id: () => "old-root", capture: () => draft, restore: () => {}, blur: () => {} })
    let route: any = { name: "session", params: { sessionID: "old-root" } }
    const navigated: string[] = []
    const info = (id: string) => ({ id, metadata: { desktop_context: { id: "owner", chat: "root", session: "root" } } })
    const color = new Proxy({}, { get: () => "#ffffff" })
    let aborted = 0
    const api: any = {
      route: { get current() { return route }, navigate: (_name: string, params: any) => {
        if (!host.allowRoute({ type: "session", sessionID: params.sessionID })) return
        navigated.push(params.sessionID); route = { name: "session", params } } },
      state: { session: { get: info, permission: () => [], question: () => [] } },
      client: { session: {
        get: async ({ sessionID }: any) => ({ data: info(sessionID) }),
        children: async () => ({ data: [] }),
        status: async () => ({ data: {} }),
        messages: async ({ sessionID }: any) => ({ data: [{ info: { id: `msg-${sessionID}` }, parts: [] }] }),
        abort: async () => { aborted++ },
      } },
      theme: { current: color },
      keymap: { dispatchCommand: () => {} },
      lifecycle: { signal: new AbortController().signal, onDispose: (fn: any) => { disposers.push(fn); return () => {} } },
    }
    await plugin.tui(api)
    await new Promise((resolve) => setTimeout(resolve, 600))
    expect(host.blocked()).toBe(false)
    expect(await host.beforeSubmit()).toBe(false) // discovery pending; no stale latch
    expect(host.blocked()).toBe(false)
    publish({ ...local, generation: 3, known_revision: "local-rev2", base_revision: "local-rev2",
      observed_head: headToken(head) })
    await new Promise((resolve) => setTimeout(resolve, 600))
    expect(host.blocked()).toBe(false)
    expect(await host.beforeSubmit()).toBe(true)
    publish(record) // confirmed external update still requires acknowledgement
    await until(() => host.blocked(), "stale overlay")
    expect(await host.beforeSubmit()).toBe(false)
    const key = (name: string) => host.overlay()!.key({ name, preventDefault() {}, stopPropagation() {} })
    key("return") // too soon after appearance: protects against an in-flight Enter
    key("escape")
    await new Promise((resolve) => setTimeout(resolve, 300))
    expect(host.blocked()).toBe(true)
    expect(navigated).toEqual([])
    // A direct navigation attempt (palette/session list/server select) is refused.
    api.route.navigate("session", { sessionID: "new-root" })
    expect(navigated).toEqual([])

    key("return")
    await until(() => navigated.length > 0, "verified handoff")
    expect(navigated).toEqual(["new-root"])
    expect(host.blocked()).toBe(false)
    expect(aborted).toBe(0)
    const commands = readFileSync(calls, "utf8").trim().split("\n").map((line) => JSON.parse(line))
    expect(commands.filter((call) => call[0] === "ensure")).toEqual([
      ["ensure", "--owner", "owner", "--chat", "root", "--member", "root", "--expected-revision", "rev2"]])
    unbindOld()
    host.bindPrompt({ id: () => "new-root", capture: () => draft, restore: (value) => { restored = value }, blur: () => {} })
    expect(restored).toEqual(draft)
    // Draft and superseded-copy history are durable, private, discoverable.
    const recovery = join(directory, "state/opencode-context/stale-recovery")
    const saved = readdirSync(recovery).map((name) => JSON.parse(readFileSync(join(recovery, name), "utf8")))
    expect(saved.some((item) => item.reason === "superseded" && item.draft.prompt.input === draft.prompt.input)).toBe(true)
    expect(saved.some((item) => item.reason === "preserved-history" && item.draft.histories[0].info.id === "old-root")).toBe(true)
  } finally {
    for (const dispose of disposers) await dispose()
    host.clear()
    process.env = previous
    rmSync(directory, { recursive: true, force: true })
  }
})
