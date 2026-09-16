// Subscription headroom, read from the quickshell usage cache.
//
// `quickshell-ai-usage` already polls Anthropic and both ChatGPT accounts for
// the bar widget and writes the result to
// `$XDG_STATE_HOME/quickshell/ai-usage.json`. The router reuses that file
// instead of polling the same endpoints again, and only shells out to refresh
// it when the cache has gone stale.
//
// Live account switching has a hard limit worth knowing about: OpenCode's
// OpenAI provider reads auth.json once, inside the auth loader, and then closes
// over that token for the life of the process (see
// packages/opencode/src/plugin/openai/codex.ts). Swapping profiles only takes
// effect for a provider that has not been initialised yet, which is why the
// switch is attempted at plugin startup. After that point the router stops
// routing to the exhausted provider instead, which works without a restart.

import { execFile } from "node:child_process"
import fs from "node:fs"
import path from "node:path"

const USAGE_BIN = "quickshell-ai-usage"
const ACCOUNT_BIN = "quickshell-ai-account"

function cachePath() {
  const base =
    process.env.XDG_STATE_HOME ??
    (process.env.HOME ? path.join(process.env.HOME, ".local", "state") : undefined)
  if (!base) return undefined
  return path.join(base, "quickshell", "ai-usage.json")
}

function run(bin, args, timeoutMs) {
  return new Promise((resolve) => {
    let done = false
    const child = execFile(bin, args, { timeout: timeoutMs }, (error, stdout) => {
      if (done) return
      done = true
      resolve(error ? undefined : stdout)
    })
    child.on("error", () => {
      if (done) return
      done = true
      resolve(undefined)
    })
  })
}

function worstWindow(provider) {
  const used = (provider?.windows ?? []).map((w) => Number(w?.used ?? 0)).filter((n) => Number.isFinite(n))
  if (!used.length) return undefined
  return Math.max(...used)
}

export function createUsage(options = {}) {
  const file = cachePath()
  const maxAgeMs = (options.maxAgeSeconds ?? 900) * 1000

  let snapshot
  let refreshing

  const read = () => {
    if (!file) return undefined
    try {
      const data = JSON.parse(fs.readFileSync(file, "utf8"))
      const providers = new Map()
      for (const provider of data?.providers ?? []) {
        const id = provider?.id
        if (!id) continue
        providers.set(id, provider)
      }
      return providers.size ? providers : undefined
    } catch {
      return undefined
    }
  }

  const stalest = (providers) => {
    let oldest = Infinity
    for (const provider of providers.values()) {
      const at = Number(provider?.fetched_at ?? 0) * 1000
      if (at < oldest) oldest = at
    }
    return oldest
  }

  const refresh = async () => {
    if (refreshing) return refreshing
    refreshing = run(USAGE_BIN, [], 20000)
      .then(() => {
        snapshot = read()
      })
      .finally(() => {
        refreshing = undefined
      })
    return refreshing
  }

  const load = () => {
    if (!snapshot) snapshot = read()
    return snapshot
  }

  return {
    /** Reload from disk; refresh in the background when the cache is stale. */
    poll() {
      snapshot = read() ?? snapshot
      const providers = snapshot
      if (!providers) return undefined
      if (Date.now() - stalest(providers) > maxAgeMs) void refresh()
      return providers
    },

    refresh,

    activeOpenAIProfile() {
      const providers = load()
      if (!providers) return undefined
      for (const [id, provider] of providers) {
        if (id.startsWith("openai-") && provider.active) return provider.profile ?? id.slice("openai-".length)
      }
      return undefined
    },

    /**
     * Remaining percentage for the subscription behind a provider id, or
     * `undefined` when there is no usage data. OpenAI resolves to whichever
     * account is currently active, since that is the one a request would spend.
     */
    headroom(providerID) {
      const providers = load()
      if (!providers) return undefined
      let provider
      if (providerID.startsWith("anthropic")) {
        provider = providers.get("anthropic")
      } else if (providerID.startsWith("openai")) {
        const active = this.activeOpenAIProfile()
        provider = active ? providers.get(`openai-${active}`) : undefined
      } else {
        // Free and local providers have no subscription to exhaust.
        return 100
      }
      if (!provider || provider.available === false) return undefined
      const used = worstWindow(provider)
      return used === undefined ? undefined : Math.max(0, 100 - used)
    },

    /**
     * Pick the OpenAI account with the most headroom, when the active one is
     * spent and the other is saved and meaningfully fresher. Returns the
     * profile switched to, or undefined.
     */
    async maybeSwitchOpenAI({ threshold = 90, minGain = 20 } = {}) {
      const providers = load()
      if (!providers) return undefined

      const accounts = []
      for (const [id, provider] of providers) {
        if (!id.startsWith("openai-")) continue
        if (!provider.saved) continue
        if (provider.available === false) continue
        const used = worstWindow(provider)
        if (used === undefined) continue
        accounts.push({ profile: provider.profile ?? id.slice("openai-".length), used, active: !!provider.active })
      }
      if (accounts.length < 2) return undefined

      const active = accounts.find((account) => account.active)
      if (!active || active.used < threshold) return undefined

      const best = accounts.filter((a) => !a.active).sort((a, b) => a.used - b.used)[0]
      if (!best || active.used - best.used < minGain) return undefined

      const out = await run(ACCOUNT_BIN, ["select", best.profile], 30000)
      if (!out) return undefined
      try {
        if (JSON.parse(out)?.ok !== true) return undefined
      } catch {
        return undefined
      }
      snapshot = undefined
      void refresh()
      return best.profile
    },
  }
}
