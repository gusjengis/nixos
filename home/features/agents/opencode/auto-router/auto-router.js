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

import {
  continuationKind,
  directiveTier,
  keywordTier,
  score,
  stripReminders,
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
  // both subscriptions; the member is chosen by remaining headroom, then kept
  // for the rest of the session so a live conversation does not bounce between
  // models and throw away its prompt cache.
  //
  // `trivial` is free (OpenCode Zen). It only ever sees turns that are short,
  // attachment-free and carry no code, so a weaker model there costs nothing
  // worse than a re-ask.
  tiers: {
    trivial: ["opencode/nemotron-3-ultra-free", "opencode/nemotron-3.5-lightning-free"],
    simple: ["anthropic/claude-haiku-4-5", "openai/gpt-5.6-luna-fast"],
    medium: ["anthropic/claude-sonnet-4-5", "openai/gpt-5.6-sol-fast"],
    complex: ["anthropic/claude-sonnet-5", "openai/gpt-5.6-terra"],
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

  fallback: "anthropic/claude-sonnet-4-5",

  // Escalation is immediate; de-escalation drops at most one tier per turn.
  // Bouncing between models mid-session throws away the prompt cache, and a
  // cache rewrite can cost more than the cheaper rate saves.
  maxDropPerTurn: 1,

  // A bare "continue" / "yes" is scored as the turn it continues, not on its
  // own four characters. With no previous turn to inherit from - a session
  // resumed after a restart - it lands here rather than on the free tier,
  // because approving unseen work is not a trivial turn.
  inheritOnContinuation: true,
  continuationFallback: "medium",

  keywordRules: [
    { keywords: ["hi", "hello", "thanks", "thank you"], tier: "trivial" },
    { keywords: ["typo", "rename", "reformat", "add a comment"], tier: "simple" },
    {
      keywords: [
        "race condition",
        "deadlock",
        "memory leak",
        "security",
        "vulnerability",
        "architecture",
        "migrate",
        "migration",
        "redesign",
        "root cause",
      ],
      tier: "reasoning",
    },
  ],

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

  // Subscription-aware routing. Reads the usage cache the quickshell bar
  // already maintains.
  usage: {
    enabled: true,
    maxAgeSeconds: 900,
    // Below this much remaining headroom a provider is skipped in favour of
    // another pool member.
    avoidBelowHeadroom: 8,
    // When the active ChatGPT account is this spent and the other saved account
    // has meaningfully more left, switch to it at startup.
    switchOpenAIAbove: 90,
    switchOpenAIMinGain: 20,
  },

  // Delegation. Two directions, for opposite reasons.
  //
  // `deep` buys reasoning the current model does not have, and costs real
  // subscription usage, so it is hard-capped.
  //
  // `quick` is free. Handing file reading, searching and summarising to it is
  // token-positive for the caller: a subagent's own context is spent on the
  // free model, and the caller only pays for the task call and the summary that
  // comes back, instead of paying for every file it would otherwise read into
  // its own window.
  escalation: {
    enabled: true,
    agent: "deep",
    maxPerTurn: 2,
    maxPerSession: 6,
    // At `reasoning` the main model already is the strong one, so advertising
    // `deep` there would only buy a second opinion at double the price.
    advertiseBelowTier: "reasoning",
  },

  offload: {
    enabled: true,
    agent: "quick",
    // Free, but not unbounded: each call still costs the caller a tool call and
    // a summary, and a model that fires fifty of them is not saving anything.
    maxPerTurn: 8,
    maxPerSession: 40,
  },

  statusFile: null,
  log: true,
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

export const AutoRouterPlugin = async ({ client }) => {
  const config = readConfig()
  if (!config.enabled) return {}

  const status = statusPath(config)
  const usage = config.usage?.enabled ? createUsage({ maxAgeSeconds: config.usage.maxAgeSeconds }) : undefined
  const sessions = new Map()
  let catalog

  const log = (level, message, extra) => {
    if (!config.log) return
    client.app.log({ body: { service: SERVICE, level, message, extra } }).catch(() => {})
  }

  // Account switching only takes effect on a provider OpenCode has not
  // initialised yet, so it is attempted once, here, before any model is used.
  if (usage) {
    usage.poll()
    usage
      .maybeSwitchOpenAI({
        threshold: config.usage.switchOpenAIAbove,
        minGain: config.usage.switchOpenAIMinGain,
      })
      .then((profile) => {
        if (profile) log("info", `switched ChatGPT account to ${profile}`, { profile })
      })
      .catch(() => {})
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
      catalog = { models: new Map() }
    }
    return catalog
  }

  const resolveTarget = async (tier, sessionID, forcedEffort) => {
    const { models } = await loadCatalog()
    const raw = config.tiers?.[tier]
    const pool = (Array.isArray(raw) ? raw : [raw]).filter(Boolean)

    const known = models.size ? pool.filter((id) => models.has(id)) : pool
    let candidates = known.length ? known : [config.fallback].filter(Boolean)
    if (!candidates.length) return undefined

    // Drop providers that have nothing left, unless that empties the pool.
    let exhausted
    if (usage) {
      const withRoom = candidates.filter((id) => {
        const left = usage.headroom(id.slice(0, id.indexOf("/")))
        return left === undefined || left > config.usage.avoidBelowHeadroom
      })
      if (withRoom.length && withRoom.length !== candidates.length) {
        exhausted = candidates.filter((id) => !withRoom.includes(id))
      }
      if (withRoom.length) candidates = withRoom
    }

    // Sticky per session and tier: re-picking every turn would change models
    // mid-conversation and invalidate the provider-side prompt cache.
    const state = sessions.get(sessionID)
    const sticky = state?.picks?.[tier]
    let picked = sticky && candidates.includes(sticky) ? sticky : undefined

    if (!picked) {
      // Most headroom first; hash as a stable tie-break.
      const ranked = [...candidates].sort((a, b) => {
        const left = usage?.headroom(a.slice(0, a.indexOf("/"))) ?? 100
        const right = usage?.headroom(b.slice(0, b.indexOf("/"))) ?? 100
        if (right !== left) return right - left
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
      providerID: parsed.providerID,
      modelID: parsed.modelID,
      variant,
      effortLabel: variant ?? (adaptive ? "auto" : "default"),
      modelName: info?.name ?? parsed.modelID,
      providerName: info?.providerName ?? parsed.providerID,
      exhausted,
    }
  }

  const readStatus = () => {
    try {
      const data = JSON.parse(fs.readFileSync(status, "utf8"))
      return data?.sessions ?? {}
    } catch {
      return {}
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
    const state = { tier, picks, delegations: {}, last }
    sessions.set(sessionID, state)
    return state
  }

  const writeStatus = (sessionID, entry) => {
    try {
      fs.mkdirSync(path.dirname(status), { recursive: true })
      let data
      try {
        data = JSON.parse(fs.readFileSync(status, "utf8"))
      } catch {
        data = undefined
      }
      if (!data || typeof data !== "object" || !data.sessions) data = { sessions: {} }

      if (entry) data.sessions[sessionID] = entry
      else delete data.sessions[sessionID]

      // Keep the file small; the TUI only ever reads the session in front of it.
      const entries = Object.entries(data.sessions)
      if (entries.length > 64) {
        entries.sort((a, b) => (b[1]?.time ?? 0) - (a[1]?.time ?? 0))
        data.sessions = Object.fromEntries(entries.slice(0, 64))
      }
      data.updated = Date.now()

      const tmp = `${status}.${process.pid}.tmp`
      fs.writeFileSync(tmp, JSON.stringify(data))
      fs.renameSync(tmp, status)
    } catch (error) {
      log("warn", "failed to write status file", { error: String(error) })
    }
  }

  const decide = (sessionID, ask, parts, previous) => {

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

    const continuation = config.inheritOnContinuation ? continuationKind(ask) : undefined

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

    // An acknowledgement asks for nothing, so it runs free even at the end of a
    // hard conversation - which is exactly where it is most worth doing, since
    // by then the turn carries the whole accumulated context. It does not move
    // the session's working tier, so the next real turn resumes where it was.
    if (continuation === "acknowledgement") {
      return { tier: "trivial", cause: "acknowledgement", signals: ["asks for nothing"], score: null, sticky: false }
    }

    const keyword = keywordTier(ask, config.keywordRules)
    const scored = score({
      ask,
      weights: config.weights,
      boundaries: config.boundaries,
      tokenThresholds: config.tokenThresholds,
      technicalKeywords: config.technicalKeywords,
    })

    let tier = scored.tier
    let cause = "heuristic"
    const signals = [...scored.signals]

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

    // The free tier exists for turns that ask for nothing: greetings,
    // acknowledgements, "thanks". Those are not cheap turns - they carry the
    // whole accumulated context - but they are ones a weak model cannot get
    // meaningfully wrong. Anything that asks for work on the repository needs a
    // model that can be trusted with tools.
    const attachments = attachmentCount(parts)
    if (
      tier === "trivial" &&
      (attachments > 0 || scored.tokens > config.tokenThresholds.simple || wantsWork(ask))
    ) {
      tier = "simple"
      signals.push("asks for work")
    }
    if (attachments > 0 && tierIndex(tier) < tierIndex("medium")) {
      tier = "medium"
      signals.push(`attachments (${attachments})`)
    }

    // Drop at most one tier per turn. Falling from `reasoning` straight to
    // `trivial` because a follow-up happened to be short is how a hard task
    // quietly loses the model that was solving it.
    if (previous && tierIndex(tier) < tierIndex(previous) - config.maxDropPerTurn) {
      tier = tierAt(tierIndex(previous) - config.maxDropPerTurn)
      signals.push(`floored from ${previous}`)
      cause = `${cause}+floor`
    }

    return { tier, cause, signals, score: scored.score }
  }

  const budget = (input, output, rule) => {
    if (!rule?.enabled) return
    if (input.tool !== "task") return
    if (output?.args?.subagent_type !== rule.agent) return

    const state = sessions.get(input.sessionID)
    if (!state) return

    const counts = (state.delegations[rule.agent] ??= { turn: 0, session: 0 })
    if (counts.turn >= rule.maxPerTurn || counts.session >= rule.maxPerSession) {
      throw new Error(
        `Delegation budget for @${rule.agent} is exhausted ` +
          `(${counts.turn}/${rule.maxPerTurn} this turn, ${counts.session}/${rule.maxPerSession} this session). ` +
          `Do this part yourself.`,
      )
    }
    counts.turn++
    counts.session++
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

      usage?.poll()

      const ask = extractAsk(output.parts, config.reminderMarkers)
      const decision = decide(sessionID, ask, output.parts, state?.tier)

      // A variant selected by hand on the Auto entry is an explicit effort
      // override and beats the tier default. Once the TUI has swapped the
      // selection to a concrete model the variant it sends belongs to that
      // model, not to Auto, so it is ignored.
      const forcedEffort = isRouter && model.variant && model.variant !== "default" ? model.variant : undefined
      const target = await resolveTarget(decision.tier, sessionID, forcedEffort)
      if (!target) {
        log("error", "no usable model for tier, leaving the request untouched", { tier: decision.tier })
        return
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

      const picks = { ...(state?.picks ?? {}), [decision.tier]: target.id }
      const delegations = state?.delegations ?? {}
      // Per-turn budgets reset when a new user turn starts.
      for (const counts of Object.values(delegations)) counts.turn = 0

      // A non-sticky decision routes this one turn without moving the session's
      // working tier.
      const tier = decision.sticky === false ? (state?.tier ?? decision.tier) : decision.tier
      sessions.set(sessionID, { tier, picks, delegations, last: target.id })

      const entry = {
        tier: decision.tier,
        sessionTier: tier,
        cause: decision.cause,
        score: decision.score,
        signals: decision.signals,
        providerID: target.providerID,
        modelID: target.modelID,
        modelName: target.modelName,
        providerName: target.providerName,
        effort: target.effortLabel,
        variant: target.variant ?? null,
        free: target.providerID === "opencode" || target.providerID === "lmstudio",
        headroom: usage?.headroom(target.providerID) ?? null,
        avoided: target.exhausted ?? null,
        time: Date.now(),
      }
      writeStatus(sessionID, entry)
      log("info", "routing decision", entry)
    },

    // Guidance text is constant so it does not churn the cached system prompt.
    "experimental.chat.system.transform": async (input, output) => {
      const state = input?.sessionID ? sessions.get(input.sessionID) : undefined
      if (!state) return

      const lines = ["## Auto model routing", "", "This turn was routed to the cheapest model judged able to handle it."]

      if (config.offload?.enabled) {
        lines.push(
          "",
          `Push grunt work to the \`${config.offload.agent}\` subagent (task tool). It runs on a free model, so anything it reads costs nothing:`,
          "- finding files, searching for symbols, tracing call sites",
          "- reading and summarising files you only need the gist of",
          "- answering narrow factual questions about the codebase",
          "",
          `Run several \`${config.offload.agent}\` calls in one message when the lookups are independent; they execute in parallel.`,
          `It cannot edit files and it is not smart. Give it one narrow, verifiable question each and check what it returns.`,
          `Limit: ${config.offload.maxPerTurn} per turn.`,
        )
      }

      if (config.escalation?.enabled && tierIndex(state.tier) < tierIndex(config.escalation.advertiseBelowTier)) {
        lines.push(
          "",
          `If part of the task genuinely needs harder reasoning than you can give it, hand that part to the \`${config.escalation.agent}\` subagent:`,
          "- non-obvious root-cause debugging",
          "- design or architecture decisions with real trade-offs",
          "- tricky algorithms, concurrency, or security-sensitive logic",
          "",
          `That one is expensive. Limit: ${config.escalation.maxPerTurn} per turn. When in doubt, do it yourself.`,
        )
      }

      if (lines.length > 3) output.system.push(lines.join("\n"))
    },

    // Budgets are enforced here rather than trusted to the prompt, because an
    // unbounded delegation path costs more than not routing down at all.
    "tool.execute.before": async (input, output) => {
      budget(input, output, config.escalation)
      budget(input, output, config.offload)
    },

    event: async ({ event }) => {
      if (event?.type === "session.deleted") {
        const sessionID = event.properties?.info?.id ?? event.properties?.sessionID
        if (sessionID) {
          sessions.delete(sessionID)
          writeStatus(sessionID, undefined)
        }
      }
    },
  }
}
