import assert from "node:assert/strict"
import test from "node:test"
import { setupLibrary } from "./plugins/context-library/index.js"

test("V2 library forwards discovery notices without registering submission gates", async () => {
  const hooks = {}, notices = []
  let disposed = false
  const ctx = {
    rpc: { register: async (definition) => {
      assert.equal(definition.id, "desktop.context-library")
      return { events: { emit: async (name, body) => notices.push({ name, body }) } }
    } },
    session: { get: async ({ sessionID }) => ({ id: sessionID, metadata: { desktop_context: { id: "owner" } } }),
      hook: async (name, callback) => { hooks[name] = callback } },
  }
  const stop = await setupLibrary(ctx, async ({ client }) => {
    assert.equal((await client.session.get({ path: { id: "ses_test" } })).data.id, "ses_test")
    await client.tui.showToast({ body: { title: "Discovery", message: "Fixture failure", variant: "error" } })
    return {
      "chat.message": async ({ sessionID }) => { if (sessionID === "ses_old") throw Error("stale fixture") },
      event: async ({ event }) => { disposed = event.type === "server.instance.disposed" },
    }
  })
  assert.deepEqual(notices, [{ name: "notice", body: { title: "Discovery", message: "Fixture failure", variant: "error" } }])
  assert.deepEqual(hooks, {})
  await stop()
  assert.equal(disposed, true)
})
