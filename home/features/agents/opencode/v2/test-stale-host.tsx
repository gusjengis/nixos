import { expect, test } from "bun:test"
import { desktopStale } from "../src/context/desktop-stale"
import { renderLocal } from "./fixture/local"

test("stale overlay blocks native route changes until a validated handoff", async () => {
  await using setup = await renderLocal()
  try {
    setup.route.navigate({ type: "session", sessionID: "ses_old" })
    desktopStale.block(() => <box />, () => {})
    setup.route.navigate({ type: "home" })
    expect(setup.route.data.type).toBe("session")
    expect((setup.route.data as any).sessionID).toBe("ses_old")
    expect(await desktopStale.beforeSubmit()).toBe(false)
    expect(() => desktopStale.handoff("ses_new", { prompt: { input: "draft", parts: [] } }, () => false,
      () => setup.route.navigate({ type: "session", sessionID: "ses_new" }))).toThrow("Freshness changed")
    expect(desktopStale.blocked()).toBe(true)
    desktopStale.handoff("ses_new", { prompt: { input: "draft", parts: [] } }, () => true,
      () => setup.route.navigate({ type: "session", sessionID: "ses_new" }))
    expect((setup.route.data as any).sessionID).toBe("ses_new")
    expect(desktopStale.blocked()).toBe(false)
  } finally { desktopStale.clear() }
})

test("host preserves full V2 attachment/draft data across remount and rejected sends", async () => {
  const draft = { prompt: { input: "draft", parts: [{ type: "file", url: "file:///image.png" }],
    v2: { text: "draft", files: [{ url: "file:///image.png" }], pasted: [], agents: [] } }, mode: "shell", cursor: 3 }
  let rejected: unknown
  const stop = desktopStale.configure({ guard: () => true, rejected: async (_id, value) => { rejected = value } })
  const unbind = desktopStale.bindPrompt({ id: () => "ses_source", capture: () => draft, restore: () => {}, blur: () => {} })
  const reject = desktopStale.submission("ses_source")
  draft.prompt.v2.text = "new typing"
  reject(new Error("stale"))
  await Bun.sleep(0)
  expect((rejected as any).prompt.v2.text).toBe("draft")
  unbind()
  expect((desktopStale.destination("ses_source").prompt as any).v2.text).toBe("new typing")
  stop()
})
