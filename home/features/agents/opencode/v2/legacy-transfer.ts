// Convert a portable V1 export with upstream's own history transformer. This
// path has no database or network side effects, and rejects decoder warnings.
import { Schema } from "effect"
import { Session } from "@opencode/schema/session"
import { transformSession } from "../database/v1-migration.js"
import { fromRow } from "./info.js"
import type { SessionTable } from "./sql.js"

export function convertLegacyTransfer(input: any) {
  if (!input?.info || !Array.isArray(input.messages)) throw new Error("Invalid legacy session export")
  if (input.info.location) return input
  const info = input.info
  if (typeof info.directory !== "string" || !info.directory.startsWith("/"))
    throw new Error("Legacy session export must have an absolute working directory")
  const base = {
    id: info.id, project_id: info.projectID ?? "global", parent_id: info.parentID ?? null,
    workspace_id: info.workspaceID ?? null, directory: info.directory, path: info.path ?? null,
    title: info.title ?? null, metadata: info.metadata ?? null, permission: null,
    agent: null, model: null, revert: info.revert ?? null, time_compacting: null,
    time_created: info.time.created, time_updated: info.time.updated,
    time_busy: null, time_idle: null, time_viewed: null, time_archived: info.time.archived ?? null,
    idle_outcome: null,
  } as unknown as typeof SessionTable.$inferSelect
  const messages = input.messages.map(({ info }: any) => ({
    id: info.id, session_id: base.id, time_created: info.time.created,
    time_updated: info.time.completed ?? info.time.created, data: JSON.stringify(info),
  }))
  const parts = input.messages.flatMap(({ info, parts }: any) => parts.map((part: any) => ({
    id: part.id, message_id: info.id, session_id: base.id,
    time_created: info.time.created, time_updated: info.time.completed ?? info.time.created,
    data: JSON.stringify(part),
  })))
  const converted = transformSession({ session: base, messages, parts })
  if (converted.warnings.length)
    throw new Error(`Legacy session export has ${converted.warnings.length} unsupported record(s); original data retained`)
  const session = fromRow({ ...base, ...converted.session })
  return {
    info: Schema.encodeSync(Session.Info)(session),
    messages: converted.messages.map((row) => ({ id: row.id, type: row.type, ...row.data })),
  }
}
