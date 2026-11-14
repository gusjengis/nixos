import { expect, mock, test } from "bun:test"

mock.module("solid-js", () => ({ createSignal: (initial) => {
  let value = initial
  return [() => value, (next) => { value = typeof next === "function" ? next(value) : next }]
} }))
const jsx = (type, props) => ({ type, props })
mock.module("@opentui/solid/jsx-runtime", () => ({ jsx, jsxs: jsx, Fragment: {} }))
mock.module("@opentui/solid/jsx-dev-runtime", () => ({ jsxDEV: jsx, Fragment: {} }))
mock.module("./history-client.mjs", () => ({
  createHistoryClient: () => ({ list: async () => ({}), observe: () => () => {}, cancel: () => {} }),
  rowStatus: () => "",
}))
const calls: string[][] = []
let retry = false
mock.module("node:child_process", () => ({ execFile: (_file, args, _options, callback) => {
  calls.push(args)
  callback(null, JSON.stringify(args[0] === "destinations" ? [
    { id: "owner", title: "Smart Home" },
    { id: "project", title: "Smart Home / Lighting", directory: "/work", retry },
  ] : {}), "")
} }))
const plugin = (await import("./tui-plugins/context-library.tsx")).default

test("palette moves selected conversation to nested context; active subagents block transfer", async () => {
  const previous = process.env.CONTEXT_ID
  process.env.CONTEXT_ID = "owner"
  const disposers: any[] = []
  try {
    calls.length = 0
    let commands: any[] = []
    let dialog: any
    let busy = false
    const toasts: any[] = []
    const routes: string[] = []
    const root = { id: "ses_root", metadata: { desktop_context: { id: "owner" } } }
    const child = { id: "ses_child", parentID: root.id, metadata: root.metadata }
    const api: any = {
      route: { current: { name: "session", params: { sessionID: child.id } }, navigate: (route) => routes.push(route) },
      state: { session: { permission: () => [], question: () => [] } },
      client: { session: {
        get: async ({ sessionID }) => ({ data: sessionID === root.id ? root : child }),
        children: async ({ sessionID }) => ({ data: sessionID === root.id ? [child] : [] }),
        status: async () => ({ data: busy ? { [child.id]: { type: "busy" } } : {} }),
      } },
      slots: { register: () => {} },
      lifecycle: { onDispose: (fn) => disposers.push(fn) },
      keymap: { registerLayer: (layer) => { commands = layer.commands; return () => {} } },
      ui: { DialogSelect: "select", DialogConfirm: "confirm",
        dialog: { replace: (render) => { dialog = render() }, clear: () => { dialog = undefined } },
        toast: (toast) => toasts.push(toast),
      },
    }
    await plugin.tui(api)
    // Native command palette queries only its own namespace.
    const palette = commands.filter((command) => command.namespace === "palette" && command.hidden !== true)
    expect(palette.map((command) => command.name)).toEqual([
      "context.chat.move", "context.chat.adopt", "context.chat.import", "context.chat.sync",
    ])
    const command = palette.find((command) => command.name === "context.chat.move")
    expect(command.title).toBe("Move session to context")
    await command.run()
    expect(dialog.type).toBe("select")
    expect(dialog.props.options).toEqual([{ title: "Smart Home / Lighting", description: "/work", value: "project" }])
    dialog.props.onSelect(dialog.props.options[0])
    expect(dialog.type).toBe("confirm")
    expect(calls.some((args) => args[0] === "move")).toBe(false)
    busy = true
    dialog.props.onConfirm()
    await Bun.sleep(20)
    expect(toasts.at(-1).message).toMatch(/subagents to finish/)
    expect(calls.some((args) => args[0] === "move")).toBe(false)
    busy = false
    await command.run()
    dialog.props.onSelect(dialog.props.options[0])
    dialog.props.onConfirm()
    await Bun.sleep(20)
    expect(calls.at(-1)).toEqual(["move", "--session", "ses_child", "--target", "project"])
    expect(routes).toEqual(["home"])
    expect(toasts.at(-1).variant).toBe("success")
    root.metadata.desktop_context.id = "project"
    retry = true
    await command.run()
    expect(dialog.props.options.find((option) => option.value === "project").description).toMatch(/finish interrupted move/)
  } finally {
    for (const dispose of disposers) dispose()
    if (previous === undefined) delete process.env.CONTEXT_ID
    else process.env.CONTEXT_ID = previous
  }
})
