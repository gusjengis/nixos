import assert from "node:assert/strict"
import test from "node:test"
import { setupLegacyHooks } from "./legacy-hooks.mjs"

function fixture() {
  const hooks = { session: {}, tool: {}, shell: {} }
  const ctx = {
    location: { directory: "/project", project: { directory: "/project" } },
    session: { get: async () => ({ location: { directory: "/project" }, agent: "build" }),
      hook: async (name, handler) => { (hooks.session[name] ??= []).push(handler) } },
    tool: { hook: async (name, handler) => { (hooks.tool[name] ??= []).push(handler) } },
    shell: { hook: async (name, handler) => { (hooks.shell[name] ??= []).push(handler) } },
  }
  return { ctx, hooks }
}

test("legacy checks reject V2 prompts, renamed tools, and direct shells without swallowing errors", async () => {
  const f = fixture(), seen = []
  await setupLegacyHooks(f.ctx, async () => ({
    "chat.message": async (_input, output) => { assert.equal(output.parts[0].text, "fixture"); throw Error("fixture denied") },
    "tool.execute.before": async (input, output) => { seen.push({ tool: input.tool, args: output.args }); throw Error("fixture denied") },
  }))
  await assert.rejects(f.hooks.session.prompt[0]({ sessionID: "ses_test", prompt: { text: "fixture" } }), /fixture denied/)
  for (const tool of ["shell", "patch", "edit", "subagent"]) {
    await assert.rejects(f.hooks.tool["execute.before"][0]({ tool, sessionID: "ses_test", id: "call", input: { command: "fixture", path: "/project/file" } }), /fixture denied/)
  }
  assert.deepEqual(seen.map((entry) => entry.tool), ["bash", "apply_patch", "edit", "task"])
  assert.equal(seen[2].args.filePath, "/project/file")
  await assert.rejects(f.hooks.shell["create.before"][0]({ command: "fixture", cwd: "/project" }), /fixture denied/)
})

test("legacy mutations remain effective on V2 tool inputs and environment", async () => {
  const f = fixture()
  await setupLegacyHooks(f.ctx, async () => ({
    "tool.execute.before": async (_input, output) => { output.args.filePath = "/project/changed" },
    "shell.env": async (_input, output) => { output.env.FIXTURE = "set" },
  }))
  const event = { tool: "edit", input: { path: "/project/original" } }
  await f.hooks.tool["execute.before"][0](event)
  assert.equal(event.input.path, "/project/changed")
  const shell = { env: {} }
  await f.hooks.shell["create.before"][1](shell)
  assert.equal(shell.env.FIXTURE, "set")
})

test("unknown legacy contracts fail initialization before any hook is registered", async () => {
  const f = fixture()
  await assert.rejects(setupLegacyHooks(f.ctx, async () => ({
    "chat.message": async () => {}, unsupported: async () => {},
  })), /Unsupported legacy hook/)
  assert.deepEqual(f.hooks.session, {})
})

test("legacy instruction additions reach all V2 request kinds, while replacements fail closed", async () => {
  const f = fixture()
  await setupLegacyHooks(f.ctx, async () => ({
    "experimental.chat.system.transform": async (_input, output) => { output.system.push("fixture instruction") },
  }))
  for (const kind of ["context", "compaction", "generate", "title"]) {
    const event = { model: { providerID: "provider", id: "model" }, system: [{ type: "text", text: "original" }] }
    await f.hooks.session[kind][0](event)
    assert.equal(event.system[1].text, "fixture instruction")
  }
  const g = fixture()
  await setupLegacyHooks(g.ctx, async () => ({
    "experimental.chat.system.transform": async (_input, output) => { output.system[0] = "replacement" },
  }))
  await assert.rejects(g.hooks.session.context[0]({ model: { providerID: "provider" }, system: [{ type: "text", text: "original" }] }), /unsupported system replacement/)
})

test("legacy message checks see user text and propagate denials and supported text additions", async () => {
  const f = fixture()
  await setupLegacyHooks(f.ctx, async () => ({
    "experimental.chat.messages.transform": async (_input, output) => {
      const last = output.messages.at(-1)
      assert.equal(last.info.role, "user")
      if (last.parts[0].text === "deny fixture") throw Error("fixture denied")
      last.parts.push({ type: "text", text: "fixture instruction" })
    },
  }))
  const event = { sessionID: "ses_test", messages: [{ role: "user", content: [{ type: "text", text: "fixture" }] }] }
  await f.hooks.session.context[0](event)
  assert.equal(event.messages[0].content.at(-1).text, "fixture instruction")
  await assert.rejects(f.hooks.session.context[0]({ sessionID: "ses_test",
    messages: [{ role: "user", content: [{ type: "text", text: "deny fixture" }] }] }), /fixture denied/)
})

test("legacy message checks retain lazy native image assets", async () => {
  const f = fixture()
  await setupLegacyHooks(f.ctx, async () => ({
    "experimental.chat.messages.transform": async (_input, output) => {
      output.messages[0].parts[0].text += " checked"
    },
  }))
  const media = { type: "media", media: { bytes: async () => new Uint8Array([1, 2, 3]) } }
  const event = { sessionID: "ses_image", messages: [{ role: "user", content: [{ type: "text", text: "image" }, media] }] }
  await f.hooks.session.context[0](event)
  assert.equal(event.messages[0].content[0].text, "image checked")
  assert.equal(event.messages[0].content[1], media)
  assert.deepEqual(await event.messages[0].content[1].media.bytes(), new Uint8Array([1, 2, 3]))
})
