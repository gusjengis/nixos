// Subscription usage comes from the same helper as the Quickshell widget.
// OpenCode's OAuth HTTP transport rereads auth for each request, so selecting
// another saved account works live. Selection is global, not session-local.
import { execFile } from "node:child_process"
import fs from "node:fs"
import path from "node:path"

function cachePath() {
  const base = process.env.XDG_STATE_HOME ?? (process.env.HOME && path.join(process.env.HOME, ".local", "state"))
  return base ? path.join(base, "quickshell", "ai-usage.json") : undefined
}

function run(bin, args, timeoutMs) {
  return new Promise((resolve) => {
    execFile(bin, args, { timeout: timeoutMs }, (error, stdout) => {
      if (error) return resolve(undefined)
      try {
        resolve(JSON.parse(stdout))
      } catch {
        resolve(undefined)
      }
    })
  })
}

export function createUsage(options = {}) {
  const command = options.run ?? run
  const now = options.now ?? Date.now
  const read = options.read ?? (() => {
    try {
      return JSON.parse(fs.readFileSync(cachePath(), "utf8"))
    } catch {
      return undefined
    }
  })
  const maxAgeMs = (options.maxAgeSeconds ?? 900) * 1000
  let snapshot
  let active
  let preparing
  let lastRefresh = -Infinity
  let invalidated = false

  const provider = (id) => snapshot?.providers?.find((entry) => entry.id === id)
  const remaining = (entry) => {
    if (!entry || entry.available === false || entry.stale || !entry.fetched_at) return undefined
    if (now() - entry.fetched_at * 1000 > maxAgeMs) return undefined
    const windows = entry.windows ?? []
    if (!windows.length) return undefined
    const values = []
    let unknown = false
    for (const window of windows) {
      if (typeof window.used !== "number" || !Number.isFinite(window.used)) {
        unknown = true
        continue
      }
      const reset = typeof window.reset === "number" ? window.reset * 1000 : Date.parse(window.reset)
      // An elapsed reset needs a new observation, not an invented 100% budget.
      if (Number.isFinite(reset) && reset <= now()) {
        unknown = true
        continue
      }
      values.push(window.used)
    }
    // One still-current exhausted window is enough to block the account,
    // even if another window has reset and needs a fresh observation.
    if (values.some((used) => used >= 100)) return 0
    if (unknown) return undefined
    return Math.max(0, Math.min(100, 100 - Math.max(...values)))
  }

  return {
    // Coalesce simultaneous turns in this plugin instance. The helper also
    // serializes account writes across processes and compares expected identity.
    async prepare() {
      if (preparing) return preparing
      preparing = (async () => {
        const cached = read()
        if (cached?.providers) {
          cached.providers = cached.providers.map((entry) => {
            const previous = provider(entry.id)
            // A failed helper refresh can leave an older last-good disk entry.
            // Do not forget its stale flag until a newer observation arrives.
            return previous?.stale && (previous.fetched_at ?? 0) >= (entry.fetched_at ?? 0) ? previous : entry
          })
        }
        snapshot = cached
        let status = await command("quickshell-ai-account", ["status"], 5000)
        active = status?.ok ? status.active : undefined
        const ids = ["anthropic", ...(status?.saved ?? []).map((id) => `openai-${id}`)]
        if (invalidated || (ids.some((id) => remaining(provider(id)) === undefined) && now() - lastRefresh >= 60_000)) {
          lastRefresh = now()
          invalidated = false
          // The helper polls both accounts; stdout retains failure/stale flags
          // that the widget's last-good disk cache intentionally omits.
          const fresh = await command("quickshell-ai-usage", [], 45_000)
          if (fresh?.providers) snapshot = fresh
          // Refresh can wait for other helper processes; honor widget changes
          // that happened while waiting instead of relying on cache flags.
          status = await command("quickshell-ai-account", ["status"], 5000)
          active = status?.ok ? status.active : undefined
        }
        if (!active || remaining(provider(`openai-${active}`)) !== 0) return undefined
        const alternatives = (status?.saved ?? [])
          .filter((id) => id !== active && provider(`openai-${id}`)?.saved)
          .map((id) => ({ id, left: remaining(provider(`openai-${id}`)) }))
          .filter((entry) => entry.left > 0)
          .sort((a, b) => b.left - a.left)
        if (!alternatives.length) return undefined
        const selected = await command("quickshell-ai-account", ["select", alternatives[0].id, active], 30_000)
        // Confirm actual identity even after a timeout: the helper might have
        // completed its write just before its parent observed failure.
        const confirmed = selected?.ok ? selected : await command("quickshell-ai-account", ["status"], 5000)
        active = confirmed?.ok ? confirmed.active : undefined
        return selected?.switched ? active : undefined
      })().finally(() => { preparing = undefined })
      return preparing
    },

    invalidate() {
      invalidated = true
    },

    activeOpenAIProfile() {
      return active
    },

    headroom(providerID) {
      if (providerID.startsWith("anthropic")) return remaining(provider("anthropic"))
      if (providerID.startsWith("openai")) return active ? remaining(provider(`openai-${active}`)) : undefined
      return 100
    },
  }
}
