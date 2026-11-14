import assert from "node:assert/strict"
import test from "node:test"
import { tuiBridge } from "./tui-bridge.mjs"
import { startTheme } from "./plugins/tmux-theme/tui.js"

test("V2 data bridge preserves live selection and traverses complete families", async () => {
  let route = { type: "session", sessionID: "ses_root" }
  const requested = [], removed = []
  const info = (id) => ({ id, location: { directory: "/project" }, parentID: id === "ses_root" ? undefined : "ses_root" })
  const ctx = {
    app: {}, theme: {}, keymap: { dispatch: (id) => requested.push(id) },
    ui: { router: { current: () => route, navigate: (value) => { route = value } } },
    data: { location: { default: () => ({ directory: "/project" }) },
      session: { get: info, permission: { list: () => [] }, form: { list: () => [] } } },
    client: { session: {
      get: async ({ sessionID }) => info(sessionID),
      list: async (query) => {
        requested.push(query)
        return query.cursor ? { data: [info("ses_two")], cursor: {} } : { data: [info("ses_one")], cursor: { next: "second-page" } }
      },
      active: async () => ({ ses_one: { type: "running" } }),
      interrupt: async (query) => removed.push(query),
    }, experimental: { session: { export: async () => ({ info: info("ses_root"), messages: [{ type: "user", text: "preserved" }] }) } } },
  }
  const bridge = tuiBridge(ctx)
  try {
    assert.equal(bridge.api.route.current.params.sessionID, "ses_root")
    assert.equal(bridge.api.state.session.get("ses_root").directory, "/project")
    assert.deepEqual((await bridge.api.client.session.children({ sessionID: "ses_root" })).data.map((row) => row.id), ["ses_one", "ses_two"])
    assert.deepEqual(requested, [{ parentID: "ses_root", limit: 100 }, { cursor: "second-page", limit: 100 }])
    bridge.api.route.navigate("home")
    assert.equal(bridge.api.route.current.name, "home")
    assert.equal((await bridge.api.client.session.messages({ sessionID: "ses_root" })).data[0].text, "preserved")
    await bridge.api.client.session.abort({ sessionID: "ses_one" })
    assert.deepEqual(removed, [{ sessionID: "ses_one" }])
    assert.equal((await bridge.api.client.session.status()).data.ses_one.type, "running")
  } finally { await bridge.close() }
  assert.equal(bridge.api.lifecycle.signal.aborted, true)
})

test("V2 theme bridge publishes semantic agent colors, bounded calls, changes and cleanup", async () => {
  const calls = []
  const ctx = {
    data: { location: { agent: { list: () => [
      { id: "build", color: "secondary" }, { id: "plan", color: "warning" },
    ] } } },
    theme: { categorical: [{ 200: "#bc8cff" }], text: { feedback: {
      warning: { base: "#e3b341" }, error: { base: "#f85149" }, success: { base: "#3fb950" }, info: { base: "#d29922" },
    } } },
  }
  const stop = startTheme(ctx, { pane: "%fixture", execute: (program, args, options, done) => {
    calls.push({ program, args, options }); done(null)
  } })
  try {
    assert.equal(calls.length, 1)
    assert.equal(calls[0].program, "tmux")
    assert.deepEqual(calls[0].options, { timeout: 500, killSignal: "SIGKILL" })
    assert.ok(calls[0].args.includes("#bc8cff"))
    assert.ok(calls[0].args.includes("#e3b341"))
    await new Promise((resolve) => setTimeout(resolve, 550))
    assert.equal(calls.length, 1, "unchanged theme generated redundant tmux writes")
    ctx.theme.categorical[0][200] = "#8250df"
    await new Promise((resolve) => setTimeout(resolve, 550))
    assert.equal(calls.length, 2)
    assert.ok(calls[1].args.includes("#8250df"))
  } finally { stop() }
  ctx.theme.categorical[0][200] = "#000000"
  await new Promise((resolve) => setTimeout(resolve, 550))
  assert.equal(calls.length, 2, "disposed plugin retained its polling timer")
})
