import { describe, expect, test } from "bun:test"
import { Effect, Layer, Schema } from "effect"
import { TodoWriteTool, Parameters } from "@/tool/todo"
import { Todo } from "@/session/todo"
import { Session } from "@/session/session"
import { SessionID, MessageID } from "@/session/schema"
import { Agent } from "@/agent/agent"
import { Truncate } from "@/tool/truncate"
import type { Tool } from "@/tool/tool"

const root = SessionID.make("ses_title_root")
const child = SessionID.make("ses_title_child")
const todos = [{ content: "Implement title updates", status: "in_progress", priority: "high" }]

function fixture(denied = false) {
  const titles = new Map([[root, "Original goal"], [child, "Child goal"]])
  const writes: unknown[] = []
  const renames: unknown[] = []
  const permissions: unknown[] = []
  const services = Layer.mergeAll(
    Layer.mock(Todo.Service, { update: (input) => Effect.sync(() => { writes.push(input) }) }),
    Layer.mock(Session.Service, {
      get: (id) => Effect.succeed({ id, title: titles.get(id), ...(id === child ? { parentID: root } : {}) } as Session.Info),
      setTitle: (input) => Effect.sync(() => { renames.push(input); titles.set(input.sessionID, input.title) }),
    }),
    Layer.mock(Agent.Service, { get: () => Effect.succeed(undefined) }),
    Layer.mock(Truncate.Service, { output: (text) => Effect.succeed({ content: text, truncated: false }) }),
  )
  const context = (sessionID = root): Tool.Context => ({
    sessionID, messageID: MessageID.make("msg_title_test"), agent: "build",
    abort: new AbortController().signal, messages: [], metadata: () => Effect.void,
    ask: (input) => Effect.sync(() => { permissions.push(input); if (denied) throw new Error("denied") }),
  })
  const run = (input: typeof Parameters.Type, sessionID = root) => Effect.runPromise(
    Effect.gen(function* () {
      const tool = yield* TodoWriteTool
      const def = yield* tool.init()
      return yield* def.execute(input, context(sessionID))
    }).pipe(Effect.provide(services)),
  )
  return { titles, writes, renames, permissions, run }
}

describe("goal-aware todowrite", () => {
  test("legacy calls update todos and preserve title/output", async () => {
    const f = fixture()
    const result = await f.run({ todos })
    expect(f.writes).toEqual([{ sessionID: root, todos }])
    expect(f.renames).toEqual([])
    expect(result.output).toBe(JSON.stringify(todos, null, 2))
    expect(result.metadata).toMatchObject({ todos })
    expect(result.metadata).not.toHaveProperty("session_title")
  })

  test("title is normalized, returned in metadata, and unchanged titles are deduplicated", async () => {
    const f = fixture()
    const result = await f.run({ todos, session_title: "  Goal-aware session titles  " })
    await f.run({ todos, session_title: "Goal-aware session titles" })
    expect(f.renames).toEqual([{ sessionID: root, title: "Goal-aware session titles" }])
    expect(result.metadata.session_title).toBe("Goal-aware session titles")
    expect(f.permissions).toHaveLength(2)
    expect(f.permissions[0]).toMatchObject({ permission: "todowrite", patterns: ["*"] })
  })

  test("child-session update cannot rename its parent", async () => {
    const f = fixture()
    await f.run({ todos, session_title: "Child objective" }, child)
    expect(f.titles.get(child)).toBe("Child objective")
    expect(f.titles.get(root)).toBe("Original goal")
  })

  test("permission denial prevents both todo and title writes", async () => {
    const f = fixture(true)
    await expect(f.run({ todos, session_title: "Denied" })).rejects.toThrow("denied")
    expect(f.writes).toEqual([])
    expect(f.renames).toEqual([])
  })

  test("invalid titles fail validation before mutating either state", async () => {
    const f = fixture()
    for (const title of ["", "   ", "two\nlines", "tab\ttitle", "escape\x1btitle", "x".repeat(101)]) {
      await expect(f.run({ todos, session_title: title })).rejects.toThrow()
    }
    expect(f.writes).toEqual([])
    expect(f.renames).toEqual([])
    expect(f.permissions).toEqual([])
    expect(Schema.decodeUnknownSync(Parameters)({ todos, session_title: "x".repeat(100) }).session_title).toHaveLength(100)
  })
})
