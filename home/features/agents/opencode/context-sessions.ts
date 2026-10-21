// Copied into the pinned OpenCode source by default.nix. No context means native behavior.
import { readFileSync } from "node:fs"
import { and, sql } from "drizzle-orm"
import { SessionTable } from "@opencode-ai/core/session/sql"

export function desktopMetadata(id: string, metadata?: Record<string, any>, parent?: Record<string, any>) {
  if (parent && !parent.desktop_context) return metadata
  const inherited = parent?.desktop_context ?? metadata?.desktop_context
  const owner = inherited?.id ?? process.env.CONTEXT_ID
  if (!owner) return metadata
  return {
    ...metadata,
    desktop_context: {
      id: owner,
      chat: parent?.desktop_context?.chat ?? id,
      session: id,
    },
  }
}

export function desktopCondition() {
  const id = process.env.CONTEXT_ID
  if (!id) return undefined
  let ids = [id]
  let hidden: string[] = []
  try {
    const scope = JSON.parse(readFileSync(process.env.OPENCODE_CONTEXT_SCOPE_FILE!, "utf8"))
    if (scope.context_id !== id || !Array.isArray(scope.ids) || !scope.ids.includes(id)) throw new Error("Invalid scope")
    ids = scope.ids
    hidden = scope.hidden ?? []
  } catch {
    // Missing/incomplete scope must never broaden visibility to sibling contexts.
  }
  return and(
    sql`json_extract(${SessionTable.metadata}, '$.desktop_context.id') IN (SELECT value FROM json_each(${JSON.stringify(ids)}))`,
    sql`${SessionTable.id} NOT IN (SELECT value FROM json_each(${JSON.stringify(hidden)}))`,
  )!
}
