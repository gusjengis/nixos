import { execFile } from "node:child_process"
import { readFile } from "node:fs/promises"
import { createHooks } from "../../../notebook/runtime.mjs"

// Keep the proven notebook ownership/revision/permission behavior shared with
// V1. This small schema bridge emits native JSON Schema rather than loading the
// V1 SDK into the V2 plugin host.
function field(json) {
  return {
    json, required: true,
    optional() { this.required = false; return this },
    describe(description) { this.json.description = description; return this },
    int() { this.json.type = "integer"; return this },
    nonnegative() { this.json.minimum = 0; return this },
    positive() { this.json.minimum = 1; return this },
  }
}
const tool = (definition) => definition
tool.schema = {
  string: () => field({ type: "string" }),
  number: () => field({ type: "number" }),
  enum: (values) => field({ type: "string", enum: values }),
}

export async function setupNotebook(ctx, { run, skill }) {
  const client = { session: { get: async ({ path }) => ({ data: await ctx.session.get({ sessionID: path.id }) }) } }
  const hooks = createHooks({ client, tool, run, skill })
  await ctx.session.hook("prompt", (event) => hooks["chat.message"](event, {}))
  await ctx.session.hook("context", async (event) => {
    const original = event.system.filter((part) => part.type === "text").map((part) => part.text)
    // V2's context hook already distinguishes primary requests from helpers;
    // the shared V1 runtime used an environment marker for that distinction.
    const system = [...original, "<env>"]
    await hooks["experimental.chat.system.transform"](event, { system })
    event.system.push(...system.slice(original.length + 1).map((text) => ({ type: "text", text })))
  })
  await ctx.session.hook("compaction", async (event) => {
    const output = { context: [] }
    await hooks["experimental.session.compacting"](event, output)
    event.system.push(...output.context.map((text) => ({ type: "text", text })))
  })
  await ctx.tool.transform((editor) => {
    for (const [name, definition] of Object.entries(hooks.tool)) {
      editor.add({
        name, description: definition.description, options: { codemode: false },
        input: {
          type: "object",
          properties: Object.fromEntries(Object.entries(definition.args).map(([name, field]) => [name, field.json])),
          required: Object.entries(definition.args).filter(([, field]) => field.required).map(([name]) => name),
          additionalProperties: false,
        },
        async execute(input, context) {
          const session = await ctx.session.get({ sessionID: context.sessionID })
          const output = await definition.execute(input, {
            sessionID: context.sessionID, agent: context.agent,
            directory: session.location.directory,
            ask: ({ permission, patterns, always, metadata }) => ctx.permission.assert({
              sessionID: context.sessionID, agent: context.agent,
              action: permission, resources: patterns, save: always, metadata,
              source: { type: "tool", messageID: context.messageID, id: context.id },
            }),
          })
          return { content: output }
        },
      })
    }
  })
  const controller = new AbortController()
  const task = (async () => {
    for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
      if (event.type === "session.deleted") {
        await hooks.event({ event: { type: event.type, properties: { info: { id: event.data.sessionID } } } })
      }
    }
  })()
  task.catch((error) => { if (!controller.signal.aborted) console.error("Notebook event stream failed", error) })
  return async () => { controller.abort(); await task.catch(() => {}) }
}

export default {
  id: "desktop.context-notebook",
  async setup(ctx) {
    const source = await readFile(new URL("../../../notebook/SKILL.md", import.meta.url), "utf8")
    const skill = source.replace(/^---\n[\s\S]*?\n---\n/, "").trim()
    const run = (owner, action, payload) => new Promise((resolve, reject) => {
      const child = execFile("context-notes", ["--context", owner, action],
        { timeout: 15000, maxBuffer: 256 * 1024 }, (error, stdout, stderr) => {
          if (error) return reject(new Error(stderr.trim() || error.message))
          try { resolve(JSON.parse(stdout)) } catch (error) { reject(error) }
        })
      child.stdin.on("error", () => {})
      child.stdin.end(JSON.stringify(payload))
    })
    return setupNotebook(ctx, { run, skill })
  },
}
