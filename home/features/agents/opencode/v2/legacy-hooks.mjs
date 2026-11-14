// Compatibility for immutable V1 hook-only integrations. Unsupported contracts
// reject initialization instead of silently dropping a registered check. This
// adapter does not implement auth, tools, or mutable V1 configuration.
const aliases = { shell: "bash", patch: "apply_patch", subagent: "task" }
const supported = new Set(["chat.message", "tool.execute.before", "tool.execute.after",
  "shell.env", "experimental.chat.system.transform", "experimental.chat.messages.transform", "experimental.session.compacting"])

function toolInput(event) {
  const args = { ...event.input }
  if (typeof args.path === "string" && args.filePath === undefined) args.filePath = args.path
  if (event.tool === "subagent" && args.subagent_type === undefined) args.subagent_type = args.agent
  return { input: { tool: aliases[event.tool] ?? event.tool, sessionID: event.sessionID, callID: event.id }, args }
}

export async function setupLegacyHooks(ctx, factory, { shell } = {}) {
  const client = {
    session: { get: async ({ path }) => {
      const info = await ctx.session.get({ sessionID: path.id })
      return { data: { ...info, directory: info.location.directory } }
    } },
    app: { log: async ({ body }) => console.log(body.message) },
  }
  const hooks = await factory({ client, directory: ctx.location.directory,
    project: { ...ctx.location.project, worktree: ctx.location.project.directory }, $: shell })
  if (!hooks || typeof hooks !== "object") throw new Error("Legacy integration did not return hooks")
  for (const name of Object.keys(hooks)) {
    if (!supported.has(name) || typeof hooks[name] !== "function")
      throw new Error(`Unsupported legacy hook contract: ${name}`)
  }
  if (hooks["chat.message"]) await ctx.session.hook("prompt", async (event) => {
    const session = await ctx.session.get({ sessionID: event.sessionID })
    const parts = [{ type: "text", text: event.prompt.text ?? "" }, ...(event.prompt.files ?? [])]
    const output = { message: { id: event.messageID, sessionID: event.sessionID, role: "user", agent: session.agent }, parts }
    await hooks["chat.message"]({ sessionID: event.sessionID, agent: session.agent,
      model: session.model && { providerID: session.model.providerID, modelID: session.model.id } }, output)
    event.prompt.text = output.parts.filter((part) => part.type === "text").map((part) => part.text).join("\n")
    event.prompt.files = output.parts.filter((part) => part.type === "file")
  })
  if (hooks["tool.execute.before"]) {
    await ctx.tool.hook("execute.before", async (event) => {
      const translated = toolInput(event)
      const output = { args: translated.args }
      await hooks["tool.execute.before"](translated.input, output)
      if (typeof event.input?.path === "string" && output.args.filePath !== translated.args.path)
        output.args.path = output.args.filePath
      event.input = output.args
    })
    // Direct user shell operations use the shell domain, not the model tool
    // domain. Retain the same pre-execution check for that path as well.
    await ctx.shell.hook("create.before", async (event) => {
      const input = { tool: "bash", sessionID: event.sessionID, callID: event.id }
      const output = { args: { command: event.command, workdir: event.cwd } }
      await hooks["tool.execute.before"](input, output)
      event.command = output.args.command
      event.cwd = output.args.workdir
    })
  }
  if (hooks["tool.execute.after"]) await ctx.tool.hook("execute.after", async (event) => {
    if (event.status !== "completed") return
    const translated = toolInput(event)
    const output = { output: typeof event.result.content === "string" ? event.result.content : JSON.stringify(event.result.content),
      metadata: event.result.metadata ?? {}, title: "" }
    await hooks["tool.execute.after"]({ ...translated.input, args: translated.args }, output)
    event.result = { ...event.result, content: output.output, metadata: output.metadata }
  })
  if (hooks["shell.env"]) await ctx.shell.hook("create.before", (event) => hooks["shell.env"](
    { cwd: event.cwd, sessionID: event.sessionID }, { env: event.env }))
  if (hooks["experimental.chat.system.transform"]) {
    for (const kind of ["context", "compaction", "generate", "title"]) await ctx.session.hook(kind, async (event) => {
      const texts = event.system.filter((part) => part.type === "text").map((part) => part.text)
      const output = { system: [...texts] }
      await hooks["experimental.chat.system.transform"]({ sessionID: event.sessionID,
        model: { providerID: event.model.providerID, id: event.model.id } }, output)
      if (output.system.slice(0, texts.length).some((text, index) => text !== texts[index]))
        throw new Error("Legacy integration attempted an unsupported system replacement")
      event.system.push(...output.system.slice(texts.length).map((text) => ({ type: "text", text })))
    })
  }
  if (hooks["experimental.session.compacting"]) await ctx.session.hook("compaction", async (event) => {
    const output = { context: [] }
    await hooks["experimental.session.compacting"]({ sessionID: event.sessionID }, output)
    event.system.push(...output.context.map((text) => ({ type: "text", text })))
  })
  if (hooks["experimental.chat.messages.transform"]) await ctx.session.hook("context", async (event) => {
    const messages = event.messages.map((message, index) => ({
      info: { role: message.role, id: `msg_legacy_${index}`, sessionID: event.sessionID },
      // Native media assets may own lazy byte readers. Keep those objects
      // intact; only text parts use the legacy mutable text contract.
      parts: message.content.map((part) => part.type === "text" ? { ...part } : part),
    }))
    const output = { messages }
    await hooks["experimental.chat.messages.transform"]({}, output)
    if (output.messages.length !== event.messages.length)
      throw new Error("Legacy integration attempted an unsupported message-list replacement")
    for (let index = 0; index < event.messages.length; index++) {
      const message = output.messages[index]
      if (message.info.role !== event.messages[index].role || message.info.id !== `msg_legacy_${index}`)
        throw new Error("Legacy integration attempted an unsupported message reordering")
      event.messages[index].content = message.parts
    }
  })
}
