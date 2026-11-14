import assert from "node:assert/strict"
import test from "node:test"
import { legacyEvents, subscribeLegacyEvents } from "./events.mjs"

const session = { id: "ses_one", parentID: "ses_root", title: "Child", agent: "plan", location: { directory: "/project" } }
const get = async (id) => { assert.equal(id, session.id); return session }
const translate = (type, data = {}) => legacyEvents({ type, data: { sessionID: session.id, ...data } }, get)

test("execution bridge retains title, child identity, mode and running/retry/completion", async () => {
  const started = await translate("session.execution.started")
  assert.equal(started[0].properties.info.parentID, "ses_root")
  assert.equal(started[0].properties.info.title, "Child")
  assert.equal(started[1].properties.info.agent, "plan")
  assert.equal(started[2].properties.status.type, "busy")
  assert.equal((await translate("session.retry.scheduled")).at(-1).properties.status.type, "retry")
  assert.equal((await translate("session.step.started")).at(-1).properties.status.type, "busy")
  assert.equal((await translate("session.execution.succeeded")).at(-1).type, "session.idle")
})

test("interruptions remain distinct from failures, and deletion needs no missing-session lookup", async () => {
  assert.deepEqual((await translate("session.execution.failed", { error: { message: "failed" } })).at(-1).properties.error, { message: "failed" })
  assert.equal((await translate("session.execution.interrupted")).at(-1).properties.error.name, "MessageAbortedError")
  assert.deepEqual(await legacyEvents({ type: "session.deleted", data: { sessionID: "gone" } }, async () => { throw Error("must not query") }), [
    { type: "session.deleted", properties: { info: { id: "gone" } } },
  ])
})

test("permission and form identifiers match later replies so attention clears", async () => {
  assert.equal((await translate("permission.asked", { id: "permission" }))[0].properties.id, "permission")
  assert.equal((await translate("permission.replied", { requestID: "permission", reply: "once" }))[0].properties.requestID, "permission")
  const asked = await translate("form.created", { form: { id: "form", sessionID: session.id,
    fields: [{ title: "Choose", description: "Pick an option" }] } })
  assert.deepEqual(asked[0].properties.questions, [{ header: "Choose", question: "Pick an option" }])
  assert.equal((await translate("form.replied", { id: "form" }))[0].properties.requestID, "form")
  assert.equal((await translate("form.cancelled", { id: "form" }))[0].type, "question.rejected")
})

test("token events do not query sessions and cleanup delivers legacy timer disposal", async () => {
  assert.deepEqual(await legacyEvents({ type: "session.text.delta" }, async () => { throw Error("must not query") }), [])
  const received = []
  const cleanup = await subscribeLegacyEvents({
    session: { get: async () => session },
    event: { subscribe: async function* ({ signal }) {
      yield { type: "session.execution.started", data: { sessionID: session.id } }
      await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true }))
    } },
  }, { event: async ({ event }) => received.push(event.type) })
  await new Promise((resolve) => setImmediate(resolve))
  await cleanup()
  assert.equal(received.at(-1), "server.instance.disposed")
  assert.ok(received.includes("session.status"))
})
