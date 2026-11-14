import { describe, expect } from "bun:test"
import { Effect, Layer, Schema, Stream } from "effect"
import { AppNodeBuilder } from "@opencode/core/effect/app-node-builder"
import { Config } from "@opencode/core/config"
import { Image } from "@opencode/core/image"
import { Permission } from "@opencode/core/permission"
import { Session } from "@opencode/core/session"
import { Tool } from "@opencode/core/tool"
import { TodoTool } from "@opencode/core/tool/plugin/todo"
import { Document, Info } from "@opencode/schema/config"
import { ConfigExperimental } from "@opencode/schema/config/experimental"
import { testEffect } from "./lib/effect"
import { imagePassthrough } from "./lib/image"
import { permissionLayer } from "./lib/permission"
import { executeTool, registerToolPlugin, toolIdentity } from "./lib/tool"

const root = Session.ID.make("ses_todo_title_root")
const child = Session.ID.make("ses_todo_title_child")
const todos = [{ content: "Upgrade safely", status: "in_progress" }] as const
const it = testEffect(AppNodeBuilder.build(Tool.node, [
  Image.node.replace(imagePassthrough), Permission.node.replace(permissionLayer()),
]))

const setup = (denied = false) => Effect.gen(function* () {
  const titles = new Map([[root, "Original"], [child, "Child"]])
  const renames: unknown[] = []
  const permissions: unknown[] = []
  yield* registerToolPlugin(TodoTool.Plugin, {
    event: { subscribe: () => Stream.never },
    session: {
      get: ({ sessionID }) => Effect.succeed({ id: sessionID, title: titles.get(sessionID) }),
      update: ({ sessionID, title }) => Effect.sync(() => { renames.push({ sessionID, title }); titles.set(sessionID, title) }),
    },
  } as any).pipe(
    Effect.provide(Layer.mock(Config.Service)({ entries: () => Effect.succeed([
      new Document({ type: "document", info: new Info({ experimental: new ConfigExperimental.Info({ todo: true }) }) }),
    ]) })),
    Effect.provide(permissionLayer({ assert: (input) => Effect.sync(() => {
      permissions.push(input)
      if (denied) throw new Error("denied")
    }) })),
  )
  const registry = yield* Tool.Service
  const run = (input: unknown, sessionID = root) => executeTool(registry, {
    sessionID, ...toolIdentity,
    call: { type: "tool-call", id: "call-title", name: TodoTool.name, input },
  })
  return { titles, renames, permissions, run }
})

describe("goal-aware V2 todos", () => {
  it.effect("legacy calls preserve titles and output", () => Effect.gen(function* () {
    const f = yield* setup()
    const result = yield* f.run({ todos })
    expect(result.status).toBe("completed")
    expect(result).toMatchObject({ output: { todos }, metadata: { todos } })
    expect(f.renames).toEqual([])
  }))
  it.effect("normalizes titles and avoids duplicate rename events", () => Effect.gen(function* () {
    const f = yield* setup()
    const result = yield* f.run({ todos, session_title: "  Safe OpenCode upgrade  " })
    yield* f.run({ todos, session_title: "Safe OpenCode upgrade" })
    expect(result).toMatchObject({ metadata: { session_title: "Safe OpenCode upgrade" } })
    expect(f.renames).toEqual([{ sessionID: root, title: "Safe OpenCode upgrade" }])
    expect(f.permissions).toHaveLength(2)
  }))
  it.effect("child title cannot change its parent", () => Effect.gen(function* () {
    const f = yield* setup()
    yield* f.run({ todos, session_title: "Child task" }, child)
    expect(f.titles.get(child)).toBe("Child task")
    expect(f.titles.get(root)).toBe("Original")
  }))
  it.effect("permission denial prevents title mutation", () => Effect.gen(function* () {
    const f = yield* setup(true)
    yield* f.run({ todos, session_title: "Denied" }).pipe(Effect.exit)
    expect(f.renames).toEqual([])
    expect(f.titles.get(root)).toBe("Original")
  }))
  it.effect("invalid title values never reach execution", () => Effect.gen(function* () {
    const f = yield* setup()
    for (const session_title of ["", "   ", "two\nlines", "tab\ttitle", "escape\x1btitle", "x".repeat(101)]) {
      const result = yield* f.run({ todos, session_title })
      expect(result.status).toBe("error")
    }
    expect(f.renames).toEqual([])
    expect(f.permissions).toEqual([])
    expect(Schema.decodeUnknownSync(TodoTool.Input)({ todos, session_title: "x".repeat(100) }).session_title).toHaveLength(100)
  }))
})
