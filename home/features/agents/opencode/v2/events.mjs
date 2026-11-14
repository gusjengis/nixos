// Translate only the event contracts used by our existing status/notification
// state machines. Model requests and permission decisions never use this bridge.
const interested = new Set([
  "session.created", "session.renamed", "session.agent.selected", "session.deleted",
  "session.execution.started", "session.execution.succeeded", "session.execution.failed",
  "session.execution.interrupted", "session.retry.scheduled", "session.step.started",
  "permission.asked", "permission.replied", "form.created", "form.replied", "form.cancelled",
])

export async function legacyEvents(event, getSession) {
  if (!interested.has(event.type)) return []
  const data = event.data
  const make = (type, properties) => ({ type, properties })
  const result = []
  const id = data.sessionID ?? data.form?.sessionID
  if (id && event.type.startsWith("session.") && event.type !== "session.deleted") {
    const session = await getSession(id)
    result.push(make("session.updated", { info: { ...session, directory: session.location.directory } }))
    if (event.type === "session.execution.started" || event.type === "session.agent.selected")
      result.push(make("message.updated", { info: { role: "user", sessionID: id, agent: session.agent } }))
  }
  switch (event.type) {
    case "session.execution.started":
    case "session.step.started":
      result.push(make("session.status", { sessionID: id, status: { type: "busy" } }))
      break
    case "session.retry.scheduled":
      result.push(make("session.status", { sessionID: id, status: { type: "retry" } }))
      break
    case "session.execution.succeeded":
      result.push(make("session.idle", { sessionID: id }))
      break
    case "session.execution.failed":
      result.push(make("session.error", { sessionID: id, error: data.error }))
      break
    case "session.execution.interrupted":
      result.push(make("session.error", { sessionID: id, error: { name: "MessageAbortedError" } }))
      break
    case "session.deleted":
      result.push(make("session.deleted", { info: { id } }))
      break
    case "permission.asked":
      result.push(make("permission.asked", data))
      break
    case "permission.replied":
      result.push(make("permission.replied", data))
      break
    case "form.created": {
      const form = data.form
      if (!form.sessionID) break
      result.push(make("question.asked", {
        id: form.id, sessionID: form.sessionID,
        questions: form.fields.map((field) => ({ header: field.title, question: field.description })),
      }))
      break
    }
    case "form.replied":
    case "form.cancelled":
      result.push(make(event.type === "form.replied" ? "question.replied" : "question.rejected", {
        requestID: data.id, sessionID: id,
      }))
      break
  }
  return result
}

export async function subscribeLegacyEvents(ctx, hooks) {
  const controller = new AbortController()
  const task = (async () => {
    for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
      const events = await legacyEvents(event, (sessionID) => ctx.session.get({ sessionID }))
      for (const event of events) {
        if (controller.signal.aborted) return
        await hooks.event?.({ event })
      }
    }
  })()
  task.catch((error) => { if (!controller.signal.aborted) console.error("Desktop event stream failed", error) })
  return async () => {
    controller.abort()
    await task.catch(() => {})
    await hooks.event?.({ event: { type: "server.instance.disposed", properties: {} } })
  }
}
