// Auto model router for OpenCode.
//
// Adds a pseudo-model `auto/auto` ("Auto") to the model list. While it is
// selected, every user prompt is classified and rewritten to a real
// provider/model before the request leaves OpenCode, so cheap turns stop
// burning the expensive subscription.
//
// How the rewrite works: `chat.message` fires after the user message object is
// built but before it is persisted, and the session loop later reads the model
// off that persisted user message. Mutating `output.message.model` in the hook
// therefore redirects the turn. See packages/opencode/src/session/prompt.ts.
//
// Not used here, deliberately: LiteLLM's proxy-side auto router. Routing this
// machine's traffic through LiteLLM would mean replacing the Anthropic and
// OpenAI *subscription* OAuth credentials with metered API keys, trading a flat
// monthly cost for per-token billing. That is the opposite of the goal. The
// classifier design is borrowed from it; the transport is not.

import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { classifierDefaults, createClassifier } from "./classifier.js"
import {
  continuationKind,
  DEFAULT_KEYWORD_RULES,
  directiveTier,
  keywordTier,
  retryRequested,
  score,
  stripReminders,
  TIERS,
  tierAt,
  tierIndex,
  wantsWork,
} from "./classify.js"
import { createUsage } from "./usage.js"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROUTER_PROVIDER = "auto"
const ROUTER_MODEL = "auto"
const SERVICE = "auto-router"

const DEFAULTS = {
  enabled: true,

  // Tier -> a model id or a pool of them. Pools exist to spread load across
  // both subscriptions; near-quality members are chosen by proven health and
  // remaining headroom. Top-quality picks stay sticky for
  // the session so live conversations preserve their prompt cache.
  //
  // Intelligence scores are from Artificial Analysis Intelligence Index v4.3 (Sept 2026).
  // Models are ordered by intelligence descending within each tier.
  //
   // `trivial` is for turns that are short, attachment-free, and carry no work,
   // where a lightweight model is cost-effective.
   tiers: {
     trivial: ["anthropic/claude-haiku-4-5", "openai/gpt-5.6-luna-fast"],
    simple: ["openai/gpt-5.6-luna-fast", "anthropic/claude-haiku-4-5"],
    medium: ["openai/gpt-5.6-sol-fast", "anthropic/claude-sonnet-5"],
    complex: ["openai/gpt-5.6-sol", "anthropic/claude-sonnet-5"],
    reasoning: ["anthropic/claude-opus-5", "openai/gpt-5.6-sol"],
  },

  // Reasoning effort per tier, for models that pick their own thinking budget
  // when no variant is set - modern Anthropic adaptive thinking. `null` leaves
  // that decision to the model, which is what it is good at. The cheap tiers
  // still pin an effort, because "let the model decide" reliably decides to
  // spend more.
  effort: {
    trivial: "none",
    simple: "none",
    medium: "low",
    complex: null,
    reasoning: null,
  },

  // Everything else has no adaptive mode, so an unset variant just means the
  // provider default and the tier would buy nothing. These are chosen
  // explicitly instead.
  nonAdaptiveEffort: {
    trivial: "none",
    simple: "none",
    medium: "low",
    complex: "medium",
    reasoning: "high",
  },

  fallback: "anthropic/claude-sonnet-5",

  // Models never to route to, whatever the catalog advertises. For models that
  // are listed but permanently unusable on this machine's credentials.
  blocked: [],

  // A model that answers a routed turn with a fatal error is taken out of the
  // pools for a while, so the same dead model is not picked again on the next
  // prompt.
  //
  // This matters more than it looks. OpenCode decides whether to retry by
  // pattern-matching the error text, and Zen reports an upstream 404 as
  // "Provider returned error" - which matches its retryable patterns. A
  // permanently dead model therefore burns the full five-attempt backoff on
  // every turn instead of failing once. See packages/opencode/src/session/retry.ts.
  quarantine: {
    enabled: true,
    // First strike. Doubled per repeat strike, capped, so a model having a bad
    // ten minutes comes back quickly while a decommissioned one stays gone.
    minutes: 60,
    maxMinutes: 10080,
    // Forget a strike record that has been clean for this long, so an old
    // outage does not keep doubling the penalty months later.
    forgetAfterMinutes: 20160,
  },

  // Within a tier, prefer a model that has actually answered before. Quarantine
  // alone would let a dead model back in the moment its sentence expires, and
  // rediscovering that costs a full retry backoff; this keeps the pool on the
  // member that works and only reaches for the other one when it has to.
  preferProven: true,

  // Keep the working tier until an explicit directive or a new session.
  // A shorter follow-up is not evidence that a cold cheaper model saves usage.
  maxDropPerTurn: 0,
  intelligenceTolerance: 2,

  // A bare "continue" / "yes" is scored as the turn it continues, not on its
  // own four characters. With no previous turn to inherit from - a session
  // resumed after a restart - it lands here rather than on the free tier,
  // because approving unseen work is not a trivial turn.
  inheritOnContinuation: true,
  continuationFallback: "medium",

  keywordRules: DEFAULT_KEYWORD_RULES,

  technicalKeywords: [],

  weights: {
    tokenCount: 0.1,
    codePresence: 0.3,
    reasoningMarkers: 0.25,
    technicalTerms: 0.25,
    simpleIndicators: 0.05,
    multiStepPatterns: 0.03,
    questionComplexity: 0.02,
  },

  boundaries: {
    trivial_simple: -0.12,
    simple_medium: 0.05,
    medium_complex: 0.22,
    complex_reasoning: 0.45,
  },

  tokenThresholds: { simple: 15, complex: 400 },
  reminderMarkers: ["<system-reminder>", "</system-reminder>"],

  // The real classifier: a small model held resident on the fleet's GPU box,
  // asked to grade each turn. Everything above is what runs when that box is
  // unreachable, which on a laptop off the tailnet is most of the time. See
  // classifier.js for the defaults and why each one is what it is.
  classifier: classifierDefaults(),

  // Subscription-aware routing. Reads the usage cache the quickshell bar
  // already maintains.
  usage: {
    enabled: true,
    maxAgeSeconds: 900,
    // Below this much remaining headroom a provider is skipped in favour of
    // another pool member.
    avoidBelowHeadroom: 8,
  },



  statusFile: null,
  log: true,
}

// Artificial Analysis Intelligence Index v4.3 scores (Sept 2026), matched to
// each tier's configured effort where a directly comparable result exists.
// Tier-aware scores matter because one model can run at different effort levels.
const MODEL_INTELLIGENCE = {
   trivial: {
     "anthropic/claude-haiku-4-5": 15,
     "openai/gpt-5.6-luna-fast": 16,
   },
  simple: {
    "openai/gpt-5.6-luna-fast": 16, // non-reasoning
    "anthropic/claude-haiku-4-5": 15, // non-reasoning
  },
  medium: {
    "openai/gpt-5.6-sol-fast": 34, // low
    "anthropic/claude-sonnet-5": 25, // low
  },
  complex: {
    "openai/gpt-5.6-sol": 39, // medium
    "anthropic/claude-sonnet-5": 38, // adaptive; max score used as upper bound
  },
  reasoning: {
    "anthropic/claude-opus-5": 48, // high reference for adaptive mode
    "openai/gpt-5.6-sol": 42, // high
  },
}

function intelligence(tier, id) {
  return MODEL_INTELLIGENCE[tier]?.[id] ?? 0
}

function deepMerge(base, override) {
  if (!override || typeof override !== "object" || Array.isArray(override)) return override ?? base
  const out = Array.isArray(base) ? [...base] : { ...base }
  for (const [key, value] of Object.entries(override)) {
    const prev = out[key]
    out[key] =
      prev &&
      typeof prev === "object" &&
      !Array.isArray(prev) &&
      value &&
      typeof value === "object" &&
      !Array.isArray(value)
        ? deepMerge(prev, value)
        : value
  }
  return out
}

function readConfig() {
  const file = path.join(HERE, "auto-router.json")
  try {
    return deepMerge(DEFAULTS, JSON.parse(fs.readFileSync(file, "utf8")))
  } catch (error) {
    if (error?.code !== "ENOENT") console.error(`[${SERVICE}] failed to read ${file}: ${error.message}`)
    return DEFAULTS
  }
}

function statusPath(config) {
  if (config.statusFile) return config.statusFile
  const base =
    process.env.XDG_STATE_HOME ??
    (process.env.HOME ? path.join(process.env.HOME, ".local", "state") : path.join(HERE, ".state"))
  return path.join(base, "opencode", "auto-router.json")
}

// Stable tie-break, so two sessions with equal headroom still spread out while
// a single session keeps landing on the same member.
function hashString(value) {
  let h = 2166136261
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

// Status codes that mean "this model will not answer", as opposed to "it is
// busy". 401/403 are deliberately absent: those are the credential's problem,
// not the model's, and taking a model out over them would empty a pool while
// the account is being re-authorised.
const FATAL_STATUS = new Set([400, 404, 405, 410, 501])

// Checked before the status code. Providers routinely report a transient
// upstream failure with a 4xx of their own, and a busy model must not be
// mistaken for a dead one.
const TRANSIENT_ERROR =
  /rate limit|rate_limit|too many requests|overloaded|capacity|try again|timed? ?out|timeout|connection|network|socket|econn|etimedout|resource exhausted|quota|billing|credit|insufficient|unauthori[sz]ed|forbidden|expired|invalid[_ ]api[_ ]key/i

// Fatal regardless of status, since some providers answer "no such model" with
// a 200-shaped error envelope.
const FATAL_ERROR =
  /not supported|unsupported|not found|does not exist|no endpoints|unknown model|no such model|decommissioned|\[40[45]\]|\b40[45]\b/i

/**
 * Decide whether an error means the model this turn was routed to is unusable.
 *
 * A false positive costs one hour of the other pool member; a false negative
 * costs every subsequent turn, because OpenCode will keep retrying a model that
 * is never going to answer. The bias is therefore towards quarantining.
 */
function fatalModelError(error) {
  if (!error) return undefined

  // Overflowing the context window or aborting says nothing about the model.
  const name = String(error.name ?? "")
  if (name && !/^(APIError|ProviderError|UnknownError)$/.test(name)) return undefined

  const data = error.data ?? {}
  const text = `${data.message ?? ""} ${data.responseBody ?? ""}`
  if (!text.trim()) return undefined
  if (TRANSIENT_ERROR.test(text)) return undefined

  const status = typeof data.statusCode === "number" ? data.statusCode : undefined
  if (FATAL_ERROR.test(text)) return { status, message: data.message ?? text.trim().slice(0, 200) }
  if (status !== undefined && FATAL_STATUS.has(status)) {
    return { status, message: data.message ?? text.trim().slice(0, 200) }
  }
  return undefined
}

function parseModelID(value) {
  const index = String(value).indexOf("/")
  if (index === -1) return undefined
  return { providerID: value.slice(0, index), modelID: value.slice(index + 1) }
}

// Flatten the user parts down to the text a human actually wrote. Attachments,
// tool plumbing and complete <system-reminder> blocks are dropped: scoring them
// makes "fix this typo" and "rewrite the scheduler" look alike, because they
// share the same harness preamble.
function extractAsk(parts, markers) {
  const chunks = []
  for (const part of parts ?? []) {
    if (part?.type !== "text" || part.synthetic || typeof part.text !== "string") continue
    chunks.push(part.text)
  }
  return stripReminders(chunks.join("\n").trim(), markers)
}

function attachmentCount(parts) {
  return (parts ?? []).filter((part) => part?.type === "file" || part?.type === "agent").length
}

export const AutoRouterPlugin = async ({ client }, overrides) => {
  const config = deepMerge(readConfig(), overrides)
  if (!config.enabled) return {}

  const status = statusPath(config)
  const usage = config.usage?.enabled ? createUsage(config.usage) : undefined
  const sessions = new Map()
  let catalog

  const log = (level, message, extra) => {
    if (!config.log) return
    client.app.log({ body: { service: SERVICE, level, message, extra } }).catch(() => {})
  }

  const classifier = createClassifier({ config: config.classifier, log })

  for (const [tier, configured] of Object.entries(config.tiers ?? {})) {
    const pool = Array.isArray(configured) ? configured : [configured]
    for (const id of pool.filter(Boolean)) {
      if (!MODEL_INTELLIGENCE[tier]?.[id]) {
        log("warn", "configured model has no intelligence score", { tier, model: id })
      }
    }
  }

  const loadCatalog = async () => {
    if (catalog) return catalog
    try {
      const result = await client.config.providers()
      const providers = result?.data?.providers ?? result?.providers ?? []
      const models = new Map()
      for (const provider of providers) {
        for (const [modelID, model] of Object.entries(provider.models ?? {})) {
          models.set(`${provider.id}/${modelID}`, {
            providerID: provider.id,
            modelID,
            name: model?.name ?? modelID,
            providerName: provider.name ?? provider.id,
            variants: Object.keys(model?.variants ?? {}),
          })
        }
      }
      catalog = { models }
    } catch (error) {
      log("warn", "provider catalog unavailable, routing without validation", { error: String(error) })
      return { models: new Map() }
    }
    return catalog
  }

  // Called when a session settles without having quarantined the model it was
  // routed to, which is the only evidence available that the model answered.
  const proved = (id) => {
    if (!config.preferProven || !id || quarantined(id)) return
    const now = Date.now()
    if (now - (health[id]?.ok ?? 0) < 60_000) return
    health[id] = { ok: now }
    mutate((data) => {
      data.health ??= {}
      data.health[id] = { ok: now }
      health = data.health
    })
  }

  // Lower sorts first. A model that has answered before beats one that is
  // merely untried, which beats one carrying a spent quarantine record.
  const trust = (id) => {
    if (!config.preferProven) return 0
    if (quarantine[id]) return 2
    return health[id]?.ok ? 0 : 1
  }

  const poolFor = (tier, models) => {
    const raw = config.tiers?.[tier]
    const pool = (Array.isArray(raw) ? raw : [raw]).filter(Boolean)
    // An unknown id is one the catalog does not advertise at all; a quarantined
    // one is advertised but has proved it will not answer.
    return (models.size ? pool.filter((id) => models.has(id)) : pool).filter((id) => !quarantined(id))
  }

  const resolveTarget = async (requested, sessionID, forcedEffort) => {
    const { models } = await loadCatalog()
    refresh()

    // Walk up from the requested tier until a tier has a usable member. Routing
    // a turn to a stronger model than it needs is the correct failure here -
    // the alternative is refusing to answer because the cheap pool is down.
    let tier = requested
    let candidates = []
    const exhausted = []
    const hasUsage = (id) => {
      const left = usage?.headroom(id.slice(0, id.indexOf("/")))
      if (left !== 0) return true
      exhausted.push(id)
      return false
    }
    for (let index = tierIndex(requested); index < TIERS.length; index++) {
      const members = poolFor(TIERS[index], models).filter(hasUsage)
      if (!members.length) continue
      tier = TIERS[index]
      candidates = members
      break
    }

    let escalated
    if (tier !== requested) escalated = { from: requested, to: tier }

    if (!candidates.length) {
      const fallback = [config.fallback].filter(Boolean)
      candidates = fallback.filter((id) => (!models.size || models.has(id)) && !quarantined(id) && hasUsage(id))
    }
    if (!candidates.length) return undefined

    // Never send a request to a subscription known to be exhausted. Low but
    // non-zero headroom remains an emergency option when every candidate is
    // below the normal avoidance threshold.
    if (usage) {
      const withRoom = candidates.filter((id) => {
        const left = usage.headroom(id.slice(0, id.indexOf("/")))
        return left === undefined || left > config.usage.avoidBelowHeadroom
      })
      if (withRoom.length && withRoom.length !== candidates.length) {
        exhausted.push(...candidates.filter((id) => !withRoom.includes(id)))
      }
      if (withRoom.length) candidates = withRoom
    }

    // Sticky per session and tier: re-picking every turn would change models
    // mid-conversation and invalidate the provider-side prompt cache.
    const state = sessions.get(sessionID)
    const sticky = state?.picks?.[tier]
    const bestIntelligence = Math.max(...candidates.map((id) => intelligence(tier, id)))
    // Treat nearby benchmark scores as peers, not a reason to discard a cache.
    candidates = candidates.filter((id) => intelligence(tier, id) >= bestIntelligence - config.intelligenceTolerance)
    let picked =
      sticky && candidates.includes(sticky) ? sticky : undefined

    if (!picked) {
      // Among near-quality candidates, prefer health and available quota.
      // Exact score and stable hash only break the remaining ties.
      const ranked = [...candidates].sort((a, b) => {
        // Lower trust score means better evidence of successful responses.
        const trusted = trust(a) - trust(b)
        if (trusted !== 0) return trusted

        // Then most headroom
        const left = usage?.headroom(a.slice(0, a.indexOf("/"))) ?? 100
        const right = usage?.headroom(b.slice(0, b.indexOf("/"))) ?? 100
        if (right !== left) return right - left

        const quality = intelligence(tier, b) - intelligence(tier, a)
        if (quality) return quality

        // Finally stable hash for session diversity
        return hashString(sessionID + a) - hashString(sessionID + b)
      })
      picked = ranked[0]
    }

    const parsed = parseModelID(picked)
    if (!parsed) return undefined

    const info = models.get(picked)

    // With no explicit variant, modern Anthropic models run adaptive thinking
    // and choose their own effort per turn. Everything else just takes the
    // provider default, which no tier would benefit from, so those get a
    // pinned effort instead.
    const adaptive = info ? info.variants.includes("xhigh") && parsed.providerID.includes("anthropic") : false
    const wanted =
      forcedEffort ?? (adaptive ? (config.effort?.[tier] ?? null) : (config.nonAdaptiveEffort?.[tier] ?? null))

    // An effort name only applies if the model actually exposes it as a
    // variant; otherwise OpenCode silently ignores it.
    const variant = wanted && (!info || info.variants.includes(wanted)) ? wanted : undefined

    return {
      id: picked,
      tier,
      escalated,
      providerID: parsed.providerID,
      modelID: parsed.modelID,
      variant,
      effortLabel: variant ?? (adaptive ? "auto" : "default"),
      modelName: info?.name ?? parsed.modelID,
      providerName: info?.providerName ?? parsed.providerID,
      exhausted,
    }
  }

  const readFile = () => {
    try {
      const data = JSON.parse(fs.readFileSync(status, "utf8"))
      if (data && typeof data === "object") return data
    } catch {
      // Missing or corrupt: start from an empty document rather than refusing
      // to route.
    }
    return {}
  }

  const readStatus = () => readFile().sessions ?? {}

  // Read-modify-write of the whole status document. Sessions, the quarantine
  // and the TUI all share one small file, so it is rewritten atomically.
  const mutate = (fn) => {
    try {
      const data = readFile()
      data.sessions ??= {}
      data.quarantine ??= {}
      fn(data)

      // Keep the file small; the TUI only ever reads the session in front of it.
      const entries = Object.entries(data.sessions)
      if (entries.length > 64) {
        entries.sort((a, b) => (b[1]?.time ?? 0) - (a[1]?.time ?? 0))
        data.sessions = Object.fromEntries(entries.slice(0, 64))
      }
      data.updated = Date.now()

      fs.mkdirSync(path.dirname(status), { recursive: true })
      const tmp = `${status}.${process.pid}.tmp`
      fs.writeFileSync(tmp, JSON.stringify(data))
      fs.renameSync(tmp, status)
      return data
    } catch (error) {
      log("warn", "failed to write status file", { error: String(error) })
      return undefined
    }
  }

  // A session resumed after a restart has no in-memory tier. The status file is
  // the last decision made for it, so the conversation keeps the model it was
  // running on instead of silently falling back to the cheap tier.
  const recover = (sessionID) => {
    const entry = readStatus()[sessionID]
    const tier = entry?.sessionTier ?? entry?.tier
    if (!tier) return undefined
    const last = entry.providerID && entry.modelID ? `${entry.providerID}/${entry.modelID}` : undefined
    const picks = last && entry.tier === tier ? { [tier]: last } : {}
    const state = { tier, picks, last }
    sessions.set(sessionID, state)
    return state
  }

  const writeStatus = (sessionID, entry) => {
    mutate((data) => {
      if (entry) data.sessions[sessionID] = entry
      else delete data.sessions[sessionID]
    })
  }

  // The quarantine is process-wide and outlives a restart: a model that is gone
  // is gone for every session, and the whole point is not to rediscover that on
  // the next prompt.
  const blocked = new Set(config.blocked ?? [])
  const initial = readFile()
  let quarantine = initial.quarantine ?? {}
  let health = initial.health ?? {}
  let quarantineMtime = 0

  // Several OpenCode processes run at once, one per pane. A model one of them
  // found to be dead should not have to be rediscovered by each of the others,
  // so the shared file is re-read whenever it changes.
  const refresh = () => {
    try {
      const stat = fs.statSync(status)
      if (stat.mtimeMs === quarantineMtime) return
      quarantineMtime = stat.mtimeMs
      const data = readFile()
      quarantine = data.quarantine ?? {}
      health = data.health ?? {}
    } catch {
      // No status file yet: nothing is quarantined.
    }
  }

  const quarantined = (id) => {
    if (blocked.has(id)) return { blocked: true }
    const entry = quarantine[id]
    if (!entry) return undefined
    if ((entry.until ?? 0) <= Date.now()) return undefined
    return entry
  }

  const punish = (id, reason) => {
    if (!config.quarantine?.enabled) return undefined

    refresh()
    const now = Date.now()
    const previous = quarantine[id]
    const forget = (config.quarantine.forgetAfterMinutes ?? 0) * 60_000
    // A strike only compounds while the model has a recent record. One outage a
    // month ago should not cost a week today.
    const strikes = previous && forget && now - (previous.time ?? 0) < forget ? (previous.strikes ?? 1) + 1 : 1

    const minutes = Math.min(
      (config.quarantine.minutes ?? 60) * Math.pow(2, strikes - 1),
      config.quarantine.maxMinutes ?? 10080,
    )
    const entry = { until: now + minutes * 60_000, time: now, strikes, minutes, reason }

    quarantine[id] = entry
    mutate((data) => {
      // Drop expired records while writing, so the file cannot grow forever.
      for (const [key, value] of Object.entries(data.quarantine)) {
        const stale = forget && now - (value?.time ?? 0) > forget
        if (stale && (value?.until ?? 0) <= now) delete data.quarantine[key]
      }
      data.quarantine[id] = entry
      quarantine = data.quarantine
    })

    // Anything holding this model as its sticky pick must let go, or the
    // session would keep asking for it until the pick changed on its own.
    for (const state of sessions.values()) {
      for (const [tier, pick] of Object.entries(state.picks ?? {})) {
        if (pick === id) delete state.picks[tier]
      }
    }

    return entry
  }

  const decide = async (sessionID, ask, parts, previous) => {

    const directive = directiveTier(ask)
    if (directive) {
      return {
        tier: directive.tier,
        cause: "directive",
        signals: [directive.directive],
        directive: directive.directive,
        score: null,
      }
    }

    const attachments = attachmentCount(parts)
    if (previous && retryRequested(ask)) {
      return {
        tier: tierAt(Math.max(tierIndex(previous) + 1, attachments ? tierIndex("medium") : 0)),
        cause: "retry-escalation",
        signals: ["previous attempt did not solve the task"],
        score: null,
      }
    }
    const continuation = config.inheritOnContinuation && !attachments ? continuationKind(ask) : undefined

    // An approval authorises work that was just proposed, so it inherits the
    // tier that proposed it.
    if (continuation === "approval") {
      return {
        tier: previous ?? config.continuationFallback,
        cause: "approval",
        signals: [previous ? "continues previous turn" : "continues an unseen turn"],
        score: null,
      }
    }

    // Reuse the working model for acknowledgements rather than sending the
    // entire accumulated conversation to a cold cheap model for one short reply.
    if (continuation === "acknowledgement") {
      return { tier: previous ?? "trivial", cause: "acknowledgement", signals: ["asks for nothing; preserves working tier"], score: null }
    }

    let tier
    let cause
    let signals
    let scoreValue = null
    let tokens
    let graded

    // Ask the model first. It returns undefined when the box is unreachable,
    // the breaker is open, or it answered with something unusable, and each of
    // those has to end up on the keyword scorer rather than stalling the turn.
    if (classifier) graded = await classifier.classify(ask, { attachments })

    if (graded?.continuation) {
      // The model read the turn as a reply to the previous one. Its own text
      // says nothing about how hard the work is, so it inherits, exactly as a
      // recognised "yes" does.
      tier = previous ?? config.continuationFallback
      cause = "continuation"
      signals = [previous ? `continues ${previous}` : "continues an unseen turn", `${graded.ms}ms`]
    } else if (graded) {
      tier = graded.tier
      cause = graded.cached ? "classifier/cached" : "classifier"
      scoreValue = graded.difficulty
      signals = [`${graded.rule ?? "?"} ${graded.difficulty}/9`]
      if (!graded.calibrated) signals.push("uncalibrated")
      if (graded.truncated) signals.push("truncated")
      if (!graded.cached) signals.push(`${graded.ms}ms`)
    } else {
      const keyword = keywordTier(ask, config.keywordRules)
      const scored = score({
        ask,
        weights: config.weights,
        boundaries: config.boundaries,
        tokenThresholds: config.tokenThresholds,
        technicalKeywords: config.technicalKeywords,
      })

      tier = scored.tier
      cause = "heuristic"
      scoreValue = scored.score
      tokens = scored.tokens
      signals = [...scored.signals]

      if (keyword && tierIndex(keyword.tier) > tierIndex(tier)) {
        tier = keyword.tier
        cause = "keyword"
        signals.push(`keyword "${keyword.keyword}"`)
      } else if (keyword && tierIndex(keyword.tier) < tierIndex(tier) && scored.signals.length <= 1) {
        // Only let a keyword pull a turn *down* when the scorer had nothing much
        // to say, so "thanks, now fix the deadlock" is not filed as a greeting.
        tier = keyword.tier
        cause = "keyword"
        signals.push(`keyword "${keyword.keyword}"`)
      }
    }

     // The trivial tier is for turns that ask for nothing: greetings,
     // acknowledgements, "thanks". Those are not cheap turns - they carry the
     // whole accumulated context - but they are lightweight. Anything that asks
     // for work on the repository needs a model that can be trusted with tools.
    if (
      tier === "trivial" &&
      (attachments > 0 || (tokens !== undefined && tokens > config.tokenThresholds.simple) || wantsWork(ask))
    ) {
      tier = "simple"
      signals.push("asks for work")
    }
    if (attachments > 0 && tierIndex(tier) < tierIndex("medium")) {
      tier = "medium"
      signals.push(`attachments (${attachments})`)
    }

    // By default do not drop tiers without an explicit directive. Falling from `reasoning` straight to
    // `trivial` because a follow-up happened to be short is how a hard task
    // quietly loses the model that was solving it.
    if (previous && tierIndex(tier) < tierIndex(previous) - config.maxDropPerTurn) {
      tier = tierAt(tierIndex(previous) - config.maxDropPerTurn)
      signals.push(`floored from ${previous}`)
      cause = `${cause}+floor`
    }

    return { tier, cause, signals, score: scoreValue, rule: graded?.rule, graded: Boolean(graded) }
  }



  return {
    "chat.message": async (_input, output) => {
      const message = output?.message
      const model = message?.model
      if (!model) return

      const sessionID = message.sessionID
      const selected = `${model.providerID}/${model.modelID}`
      const isRouter = model.providerID === ROUTER_PROVIDER && model.modelID === ROUTER_MODEL

      // The TUI re-reads the model off the last user message when a session
      // comes into view, so the rewrite this plugin performs immediately
      // replaces the visible "Auto" selection with whatever it routed to. From
      // then on the prompt arrives already bound to that concrete model.
      //
      // A prompt that arrives on exactly the model this session was last routed
      // to is therefore treated as still being in Auto. Anything else is a
      // deliberate choice by the user and turns routing off for the session.
      const state = sessions.get(sessionID) ?? recover(sessionID)
      if (!isRouter && state?.last !== selected) {
        if (state) {
          sessions.delete(sessionID)
          writeStatus(sessionID, undefined)
        }
        return
      }

      const switched = await usage?.prepare()
      if (switched) log("info", "switched exhausted ChatGPT account", { profile: switched })

      const ask = extractAsk(output.parts, config.reminderMarkers)
      const decision = await decide(sessionID, ask, output.parts, state?.tier)

      // A variant selected by hand on the Auto entry is an explicit effort
      // override and beats the tier default. Once the TUI has swapped the
      // selection to a concrete model the variant it sends belongs to that
      // model, not to Auto, so it is ignored.
      const forcedEffort = isRouter && model.variant && model.variant !== "default" ? model.variant : undefined
      const target = await resolveTarget(decision.tier, sessionID, forcedEffort)
      if (!target) {
        throw new Error(`Auto router: no usable model for ${decision.tier}; subscriptions may be exhausted or models unavailable. Check usage or choose a model manually.`)
      }

      message.model = { providerID: target.providerID, modelID: target.modelID, variant: target.variant }

      // Strip the routing directive so the model never sees "!deep".
      if (decision.directive) {
        const token = new RegExp(
          `(^|\\s)${decision.directive.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?=\\s|$)`,
          "i",
        )
        for (const part of output.parts ?? []) {
          if (part?.type !== "text" || part.synthetic || typeof part.text !== "string") continue
          part.text = part.text.replace(token, "$1").trim()
        }
      }

      const picks = { ...(state?.picks ?? {}), [target.tier]: target.id }

      // Preserve the actual working tier, including availability escalation.
      const tier = target.tier
      sessions.set(sessionID, { tier, picks, last: target.id })

      const entry = {
        tier: target.tier,
        // Only set when the tier the classifier asked for had no usable model
        // left and the request was routed up to find one.
        requestedTier: target.escalated ? decision.tier : undefined,
        sessionTier: tier,
        cause: decision.cause,
        score: decision.score,
        // Whether the local model graded this turn or the keyword scorer stood
        // in for it. The status line shows the difference, because a router
        // running on the fallback is a router making worse decisions and that
        // should not be invisible.
        graded: decision.graded,
        rule: decision.rule ?? null,
        signals: decision.signals,
        providerID: target.providerID,
        modelID: target.modelID,
        modelName: target.modelName,
        providerName: target.providerName,
        effort: target.effortLabel,
        variant: target.variant ?? null,
        intelligence: intelligence(target.tier, target.id) || null,
        free: target.providerID === "opencode" || target.providerID === "lmstudio",
        headroom: usage?.headroom(target.providerID) ?? null,
        account: target.providerID === "openai" ? usage?.activeOpenAIProfile() ?? null : null,
        avoided: target.exhausted ?? null,
        time: Date.now(),
      }
      writeStatus(sessionID, entry)
      log("info", "routing decision", entry)
    },





    event: async ({ event }) => {
      if (event?.type === "session.deleted") {
        const sessionID = event.properties?.info?.id ?? event.properties?.sessionID
        if (sessionID) {
          sessions.delete(sessionID)
          writeStatus(sessionID, undefined)
        }
        return
      }

      // Only count idle as success when this turn did not report an error.
      if (event?.type === "session.idle") {
        const sessionID = event.properties?.sessionID
        const state = sessions.get(sessionID)
        if (state && !state.failed) proved(state.last)
        return
      }

      if (event?.type !== "session.error") return

      const sessionID = event.properties?.sessionID
      if (!sessionID) return

      // Only models this plugin chose are quarantined. A model the user picked
      // by hand failing is their business, and the error carries no model of its
      // own to attribute it to.
      const state = sessions.get(sessionID)
      const id = state?.last
      if (!id) return
      state.failed = true
      const error = event.properties?.error
      const errorText = `${error?.data?.message ?? ""} ${error?.data?.responseBody ?? ""}`
      if (id.startsWith("openai/") && /usage_limit|usage limit|quota|rate.limit|too many requests/i.test(errorText)) usage?.invalidate()

      const fatal = fatalModelError(error)
      if (!fatal) return

      const entry = punish(id, fatal.message)
      if (!entry) return

      log("warn", "quarantined a model after a fatal error", {
        model: id,
        status: fatal.status ?? null,
        strikes: entry.strikes,
        minutes: entry.minutes,
        until: new Date(entry.until).toISOString(),
        message: fatal.message,
      })
    },
  }
}
