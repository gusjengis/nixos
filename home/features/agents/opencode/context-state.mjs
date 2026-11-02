// Shared device-local readiness adapter; deliberately outside plugin discovery.
import { readFileSync, statSync } from "node:fs"
import { createHash } from "node:crypto"

const fresh = new Set(["local_only", "current_as_known", "unknown", "outdated", "conflict", "deleted"])
const available = new Set(["local", "portable_only", "waiting_data", "missing_workdir", "unavailable"])
export const conversationKey = (owner, chat) => `${owner}/${chat}`
export const statePath = (env = process.env) => env.OPENCODE_CONTEXT_STATE_FILE ??
  (env.OPENCODE_CONTEXT_SCOPE_FILE ? `${env.OPENCODE_CONTEXT_SCOPE_FILE}.state.json` : undefined)

export function readState(path) {
  if (!path) throw new Error("No conversation state path")
  let value
  try { value = JSON.parse(readFileSync(path, "utf8")) }
  catch (error) {
    if (error.code === "ENOENT") return { version: 1, generation: 0, conversations: {} }
    throw error
  }
  if (value.version !== 1 || !Number.isSafeInteger(value.generation) || value.generation < 0 ||
      !value.conversations || typeof value.conversations !== "object" || Array.isArray(value.conversations)) {
    throw new Error("Invalid conversation state")
  }
  for (const [key, record] of Object.entries(value.conversations)) {
    if (!record || key !== conversationKey(record.owner, record.chat) || !fresh.has(record.freshness) ||
        !available.has(record.availability) || !record.members || typeof record.members !== "object" ||
        Array.isArray(record.members) || !record.operation || typeof record.operation !== "object") {
      throw new Error("Invalid conversation record")
    }
  }
  return value
}

const headCache = new Map()
export function headToken(path) {
  try {
    const stat = statSync(path, { bigint: true })
    const identity = `${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeNs}:${stat.ctimeNs}`
    const cached = headCache.get(path)
    if (cached?.identity === identity) return cached.token
    const token = createHash("sha256").update(readFileSync(path)).digest("hex")
    if (headCache.size >= 256) headCache.delete(headCache.keys().next().value)
    headCache.set(path, { identity, token })
    return token
  }
  catch (error) { if (error.code === "ENOENT") return null; throw error }
}

export function verdict(snapshot, marker, nativeID, options = {}) {
  const record = snapshot.conversations[conversationKey(marker?.id, marker?.chat)]
  const result = (allowed, code) => ({ allowed, code, record, generation: record?.generation ?? snapshot.generation })
  if (!marker?.id || !marker?.chat) return result(false, "unverified")
  if (!record) return result(true, options.initial ? "local_only" : "unknown")
  if (["outdated", "conflict", "deleted"].includes(record.freshness)) return result(false, record.freshness)
  // The replacement can be current while this particular native copy is old.
  const mapped = record.members[marker.session] ?? (marker.session === marker.chat ? record.selected_root : undefined)
  if (mapped && mapped !== nativeID) return result(false, "outdated")
  if (!mapped && record.selected_root && nativeID !== record.selected_root && options.rootID !== record.selected_root) return result(false, "unverified")
  if (record.known_revision != null && record.base_revision !== record.known_revision) return result(false, "outdated")
  if (record.availability !== "local") return result(false,
    record.availability === "waiting_data" || record.availability === "portable_only" ? "waiting_data" : "unavailable")
  if (options.headChanged) return result(false, "waiting_data")
  return result(true, record.freshness === "local_only" ? "local_only" :
    record.freshness === "unknown" ? "unknown" : "ready")
}

export function readVerdict(path, marker, nativeID, options = {}) {
  try {
    const snapshot = readState(path)
    const record = snapshot.conversations[conversationKey(marker?.id, marker?.chat)]
    const headChanged = Boolean(record?.head_path && headToken(record.head_path) !== record.observed_head)
    return verdict(snapshot, marker, nativeID, { ...options, headChanged })
  } catch (error) {
    return { allowed: false, code: "state_invalid", generation: null, error: error.message }
  }
}

export function observeState(path, callback, { interval = 250 } = {}) {
  let last
  let disposed = false
  const poll = () => {
    if (disposed) return
    try {
      const snapshot = readState(path)
      const heads = {}
      for (const record of Object.values(snapshot.conversations)) {
        if (record.head_path && !(record.head_path in heads)) heads[record.head_path] = headToken(record.head_path)
      }
      const changedHeads = [...new Set(Object.values(snapshot.conversations)
        .filter(record => record.head_path && heads[record.head_path] !== record.observed_head)
        .map(record => record.head_path))]
      const token = JSON.stringify([snapshot.generation, heads])
      if (token !== last) { last = token; callback(snapshot, { changedHeads }) }
    } catch (error) {
      const token = `error:${error.message}`
      if (token !== last) { last = token; callback(null, { error }) }
    }
  }
  const timer = setInterval(poll, interval)
  timer.unref?.()
  poll()
  return () => { disposed = true; clearInterval(timer) }
}

export class ConversationFreshnessError extends Error {
  constructor(result) {
    const messages = {
      outdated: "Newer portable conversation available. Open the latest verified copy before sending.",
      conflict: "Conversation has conflicting histories. Preserve and resolve both copies before sending.",
      deleted: "Conversation was deleted in portable history. Existing local history is retained.",
      waiting_data: "Conversation update is arriving. Wait for verified history before sending.",
      unavailable: "Conversation history or working directory is unavailable.",
      unverified: "Cannot verify the selected conversation copy.",
      state_invalid: "Conversation freshness state is invalid. Refresh portable history before sending.",
    }
    super(messages[result.code] ?? "Cannot verify conversation freshness")
    this.name = "ConversationFreshnessError"
    this.code = result.code
    this.generation = result.generation
  }
}

// Used by native prompt/command/shell/loop entry guards as well as plugin hooks.
// rootID must come from verified native ancestry, never from a caller's request.
export function assertFreshness(session, options = {}, env = process.env) {
  const owner = env.CONTEXT_ID
  if (!owner || !env.OPENCODE_CONTEXT_SCOPE_FILE || env.OPENCODE_CONTEXT_HELPER) return
  let scope
  try { scope = JSON.parse(readFileSync(env.OPENCODE_CONTEXT_SCOPE_FILE, "utf8")) }
  catch { throw new ConversationFreshnessError({ code: "state_invalid" }) }
  if (scope.context_id !== owner) throw new ConversationFreshnessError({ code: "state_invalid" })
  const marker = session.metadata?.desktop_context
  if (!marker || !(scope.ids ?? [owner]).includes(marker.id)) {
    throw new ConversationFreshnessError({ code: "unverified" })
  }
  if (scope.hidden?.includes(session.id) || scope.hidden?.includes(options.rootID)) {
    throw new ConversationFreshnessError({ code: "outdated" })
  }
  const result = readVerdict(statePath(env), marker, session.id, options)
  if (!result.allowed) throw new ConversationFreshnessError(result)
  return result
}
