import { test, expect, mock, afterEach } from "bun:test"

// Exercise actual native bridge code without loading real terminal renderer.
// PTY/render acceptance is owned by OC1 against OC8's combined native build.
let cleanup: (() => void)[] = []
mock.module("solid-js", () => ({
  createSignal: (initial: any) => {
    let value = initial
    return [() => value, (next: any) => { value = next }]
  },
  Show: () => undefined,
  onCleanup: (callback: () => void) => cleanup.push(callback),
}))
mock.module("@opentui/solid", () => ({ useTerminalDimensions: () => () => ({ width: 80, height: 24 }) }))
mock.module("@opentui/solid/jsx-runtime", () => ({ jsx: () => undefined, jsxs: () => undefined }))
mock.module("@opentui/solid/jsx-dev-runtime", () => ({ jsxDEV: () => undefined }))
const { desktopStale: host, installDesktopStaleKeys } = await import("./context-stale-host")
const empty = { prompt: { input: "", parts: [] }, mode: "normal", cursor: 0 }

afterEach(() => {
  host.clear()
  for (const callback of cleanup) callback()
  cleanup = []
})

test("route permit is one-shot, target-specific, validated synchronously", () => {
  host.block(() => null, () => {})
  expect(host.allowRoute({ type: "home" })).toBe(false)
  expect(host.allowRoute({ type: "session", sessionID: "old" })).toBe(false)
  expect(() => host.handoff("latest", empty, () => false, () => { throw new Error("must not route") })).toThrow(/Freshness/)
  expect(host.blocked()).toBe(true)
  host.handoff("latest", empty, () => true, () => {
    expect(host.allowRoute({ type: "home" })).toBe(false)
    expect(host.allowRoute({ type: "session", sessionID: "other" })).toBe(false)
    expect(host.allowRoute({ type: "session", sessionID: "latest" })).toBe(true)
    expect(host.allowRoute({ type: "session", sessionID: "latest" })).toBe(false)
  })
  expect(host.blocked()).toBe(false)
})

test("pending draft applies only to selected target; no accidental stale remount restore", () => {
  let restored: any
  const snapshot = { prompt: { input: "draft", parts: [{ type: "text", text: "expanded" }] }, mode: "shell", cursor: 3 }
  const old = host.bindPrompt({ id: () => "old", capture: () => snapshot, restore: () => {}, blur: () => {} })
  host.block(() => null, () => {})
  host.handoff("latest", snapshot, () => true, () => {})
  old()
  const unbindWrong = host.bindPrompt({ id: () => "other", capture: () => empty, restore: () => { throw new Error("wrong draft") }, blur: () => {} })
  unbindWrong()
  const unbind = host.bindPrompt({ id: () => "latest", capture: () => empty, restore: (draft) => { restored = draft }, blur: () => {} })
  expect(restored).toEqual(snapshot)
  expect(host.destination("old")).toEqual(snapshot)
  unbind()
})

test("overlay blocks all submissions including programmatic PromptRef.submit", async () => {
  let guarded = 0
  const off = host.configure({ guard: () => { guarded++; return true }, rejected: async () => {} })
  expect(await host.beforeSubmit()).toBe(true)
  host.block(() => null, () => {})
  expect(await host.beforeSubmit()).toBe(false)
  expect(guarded).toBe(1)
  off()
})

test("Escape, Ctrl+C, arbitrary keys captured; no underlying key propagation", () => {
  let callback: any, priority: number | undefined, disposed = false
  const seen: string[] = []
  installDesktopStaleKeys({ intercept: (_kind: string, handler: any, options: any) => {
    callback = handler; priority = options.priority
    return () => { disposed = true }
  } })
  host.block(() => null, (event) => seen.push(event.name))
  for (const name of ["escape", "c", "return", "a"]) {
    let prevented = false, stopped = false
    callback({ event: { name, preventDefault: () => { prevented = true }, stopPropagation: () => { stopped = true } } })
    expect(prevented && stopped).toBe(true)
    expect(host.blocked()).toBe(true)
  }
  expect(seen).toEqual(["escape", "c", "return", "a"])
  expect(priority).toBe(10000)
  callback({ event: { name: "return", repeated: true, preventDefault() {}, stopPropagation() {} } })
  expect(seen.length).toBe(4)
  cleanup.pop()?.()
  expect(disposed).toBe(true)
})

test("rejected submission retains pre-clear structured draft independently of later typing", async () => {
  let current = { prompt: { input: "before", parts: [] }, mode: "normal", cursor: 1 }
  let rejected: any
  const unbind = host.bindPrompt({ id: () => "old", capture: () => current, restore: () => {}, blur: () => {} })
  const off = host.configure({ guard: () => true, rejected: async (id, draft, error) => { rejected = { id, draft, error } } })
  const reject = host.submission("old")
  current = { ...empty, prompt: { input: "newer typing", parts: [] } }
  reject("stale")
  await Promise.resolve()
  expect(rejected.draft.prompt.input).toBe("before")
  expect(host.capture().prompt.input).toBe("newer typing")
  off()
  unbind()
})

test("TSX plugin and native host syntax compile with Bun transpiler", async () => {
  const transpiler = new Bun.Transpiler({ loader: "tsx" })
  for (const name of ["context-stale-host.tsx", "tui-plugins/context-stale.tsx"]) {
    expect(transpiler.transformSync(await Bun.file(new URL(name, import.meta.url)).text())).toBeString()
  }
})
