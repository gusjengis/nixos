import { readFileSync, realpathSync } from "node:fs"

export function assertProfileHandoff(sessionID, env = process.env) {
  if (!env.OPENCODE_HANDOFF_FILE) return
  const profile = JSON.parse(readFileSync(env.OPENCODE_HANDOFF_FILE, "utf8"))
  if (profile.database && env.OPENCODE_DB &&
      (env.OPENCODE_DB === ":memory:" || realpathSync(profile.database) !== realpathSync(env.OPENCODE_DB))) return
  if (profile.pending?.some((record) => record.ids.some((id) => sessionID === id || sessionID.startsWith(id + "_"))))
    throw new Error("This conversation is completing its V1 history handoff; other conversations remain available")
}
