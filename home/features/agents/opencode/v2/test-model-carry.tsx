import { expect, test } from "bun:test"
import { agent, model, renderLocal, session } from "./fixture/local"

test("model choice and variant follow Plan/Build switches before first submission", async () => {
  await using setup = await renderLocal({
    agents: [agent("build"), agent("plan")],
    models: [model("first"), model("chosen", ["low", "high"])],
  })
  setup.local.model.set({ providerID: "provider", modelID: "chosen" })
  setup.local.model.variant.set("high")
  setup.local.agent.set("plan")
  expect(setup.local.model.selection()).toEqual({ providerID: "provider", modelID: "chosen", variant: "high" })
  setup.local.agent.set("build")
  expect(setup.local.model.selection()?.modelID).toBe("chosen")
})

test("existing session selection wins over per-agent defaults when switching modes", async () => {
  await using setup = await renderLocal({
    agents: [agent("build"), agent("plan", { providerID: "provider", id: "first" })],
    models: [model("first"), model("chosen", ["high"])],
    sessions: [session("ses_shared", { providerID: "provider", id: "chosen", variant: "high" })],
  })
  await setup.data.session.sync("ses_shared")
  setup.route.navigate({ type: "session", sessionID: "ses_shared" })
  setup.local.agent.set("plan")
  expect(setup.local.model.selection()).toEqual({ providerID: "provider", modelID: "chosen", variant: "high" })
})

test("changing model after a mode switch remains shared, without leaking into another session", async () => {
  await using setup = await renderLocal({
    agents: [agent("build"), agent("plan")],
    models: [model("first"), model("chosen")],
    sessions: [
      session("ses_one", { providerID: "provider", id: "first" }),
      session("ses_two", { providerID: "provider", id: "first" }),
    ],
  })
  await Promise.all([setup.data.session.sync("ses_one"), setup.data.session.sync("ses_two")])
  setup.route.navigate({ type: "session", sessionID: "ses_one" })
  setup.local.agent.set("plan")
  setup.local.model.set({ providerID: "provider", modelID: "chosen" })
  setup.local.agent.set("build")
  expect(setup.local.model.current()?.modelID).toBe("chosen")
  setup.route.navigate({ type: "session", sessionID: "ses_two" })
  expect(setup.local.model.current()?.modelID).toBe("first")
})
