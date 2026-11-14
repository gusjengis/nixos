import { describe, expect } from "bun:test"
import { writeFile } from "node:fs/promises"
import path from "node:path"
import { Cause, Effect, Exit } from "effect"
import { Bus } from "@opencode/core/bus"
import { Database } from "@opencode/core/database/database"
import { AppNodeBuilder } from "@opencode/core/effect/app-node-builder"
import { Location } from "@opencode/core/location"
import { LocationServiceMap } from "@opencode/core/location-service-map"
import { Project } from "@opencode/core/project"
import { AbsolutePath } from "@opencode/core/schema"
import { Session } from "@opencode/core/session"
import { SessionExecution } from "@opencode/core/session/execution"
import { SessionProjector } from "@opencode/core/session/projector"
import { SessionStore } from "@opencode/core/session/store"
import { LayerNode } from "@opencode/util/effect/layer-node"
import { promptLocationNode } from "./fixture/prompt-location"
import { tmpdirScoped } from "./fixture/tmpdir"
import { testEffect } from "./lib/effect"
import { globalProjectNode } from "./lib/project"

const it = testEffect(AppNodeBuilder.build(
  LayerNode.group([Database.node, Bus.node, SessionProjector.node, SessionStore.node, Session.node]),
  [Bus.node.replace(Bus.configured({ persist: true })), Project.node.replace(globalProjectNode),
    SessionExecution.node.replace(SessionExecution.noopLayer), LocationServiceMap.node.replace(promptLocationNode)],
))
const location = Location.Ref.make({ directory: AbsolutePath.make("/project") })

function environment<A, E, R>(body: Effect.Effect<A, E, R>) {
  return Effect.gen(function* () {
    const keys = ["CONTEXT_ID", "OPENCODE_CONTEXT_SCOPE_FILE", "OPENCODE_CONTEXT_HELPER", "OPENCODE_HANDOFF_FILE"]
    const saved = Object.fromEntries(keys.map((key) => [key, process.env[key]]))
    delete process.env.OPENCODE_CONTEXT_HELPER
    return yield* body.pipe(Effect.ensuring(Effect.sync(() => {
      for (const key of keys) {
        if (saved[key] === undefined) delete process.env[key]
        else process.env[key] = saved[key]
      }
    })))
  })
}

describe("desktop context V2 sessions", () => {
  it.effect("pending V1 handoff blocks contextless prompt admission", () => environment(Effect.gen(function* () {
    delete process.env.CONTEXT_ID
    const temporary = yield* tmpdirScoped()
    const sessions = yield* Session.Service
    const session = yield* sessions.create({ location })
    process.env.OPENCODE_HANDOFF_FILE = path.join(temporary.path, "handoff.json")
    yield* Effect.promise(() => writeFile(process.env.OPENCODE_HANDOFF_FILE!, JSON.stringify({ pending: [{ ids: [session.id] }] })))
    const result = yield* sessions.prompt({ sessionID: session.id, text: "pending fixture" }).pipe(Effect.exit)
    expect(Exit.isFailure(result)).toBe(true)
    if (Exit.isFailure(result)) expect(Cause.pretty(result.cause)).toContain("V1 history handoff")
    expect(yield* sessions.inbox(session.id)).toEqual([])
  })))
  it.effect("assigns and inherits ownership; arbitrary metadata updates cannot move ownership", () => environment(Effect.gen(function* () {
    process.env.CONTEXT_ID = "owner"
    const sessions = yield* Session.Service
    const root = yield* sessions.create({ location, metadata: { custom: "root" } })
    const child = yield* sessions.create({ parentID: root.id, metadata: { custom: "child" } })
    expect(root.metadata).toEqual({ custom: "root", desktop_context: { id: "owner", chat: root.id, session: root.id } })
    expect(child.metadata).toEqual({ custom: "child", desktop_context: { id: "owner", chat: root.id, session: child.id } })
    yield* sessions.setMetadata({ sessionID: child.id, metadata: { custom: "updated", desktop_context: { id: "sibling" } } })
    expect((yield* sessions.get(child.id)).metadata).toEqual({ custom: "updated", desktop_context: child.metadata!.desktop_context })
  })))

  it.effect("does not adopt a child of an unowned conversation", () => environment(Effect.gen(function* () {
    delete process.env.CONTEXT_ID
    const sessions = yield* Session.Service
    const root = yield* sessions.create({ location })
    process.env.CONTEXT_ID = "owner"
    const child = yield* sessions.create({ parentID: root.id })
    expect(child.metadata?.desktop_context).toBeUndefined()
  })))

  it.effect("scope filters retain descendants, hide superseded rows, and fail closed on missing scope", () => environment(Effect.gen(function* () {
    const temporary = yield* tmpdirScoped()
    const scope = path.join(temporary.path, "scope.json")
    const sessions = yield* Session.Service
    const store = yield* SessionStore.Service
    process.env.CONTEXT_ID = "owner"
    const own = yield* sessions.create({ location })
    process.env.CONTEXT_ID = "descendant"
    const descendant = yield* sessions.create({ location })
    process.env.CONTEXT_ID = "sibling"
    yield* sessions.create({ location })
    process.env.CONTEXT_ID = "owner"
    process.env.OPENCODE_CONTEXT_SCOPE_FILE = scope
    expect((yield* store.list()).map((item) => item.id)).toEqual([own.id])
    yield* Effect.promise(() => writeFile(scope, JSON.stringify({ context_id: "owner", ids: ["owner", "descendant"], hidden: [own.id] })))
    expect((yield* store.list()).map((item) => item.id)).toEqual([descendant.id])
  })))

  it.effect("freshness state never gates local continuation", () => environment(Effect.gen(function* () {
    const temporary = yield* tmpdirScoped()
    process.env.CONTEXT_ID = "owner"
    process.env.OPENCODE_CONTEXT_SCOPE_FILE = path.join(temporary.path, "scope.json")
    const sessions = yield* Session.Service
    const root = yield* sessions.create({ location })
    const child = yield* sessions.create({ parentID: root.id })
    yield* Effect.promise(() => writeFile(process.env.OPENCODE_CONTEXT_SCOPE_FILE!, JSON.stringify({ context_id: "owner", ids: ["owner"], hidden: [root.id, child.id] })))
    const store = yield* SessionStore.Service
    expect((yield* store.list({ parentID: root.id })).map((session) => session.id)).toEqual([child.id])
    yield* sessions.resume(child.id)
    const result = yield* sessions.prompt({ sessionID: child.id, text: "local continuation", resume: false }).pipe(Effect.exit)
    expect(Exit.isSuccess(result)).toBe(true)
  })))
})
