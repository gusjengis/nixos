// Prompt complexity classifier for the Auto model router.
//
// Deliberately dependency-free and synchronous: it runs on every prompt
// submission, so it must not add latency or network calls. The dimensions and
// the escalate-on-two-reasoning-markers rule follow LiteLLM's complexity
// router, which is the closest published prior art.
//
// https://docs.litellm.ai/docs/proxy/auto_routing

export const TIERS = ["trivial", "simple", "medium", "complex", "reasoning"]

export const DEFAULT_KEYWORD_RULES = [
  { keywords: ["hi", "hello", "thanks", "thank you"], tier: "trivial" },
  { keywords: ["typo", "rename", "reformat", "add a comment"], tier: "simple" },
  {
    keywords: ["race condition", "deadlock", "memory leak", "security", "vulnerability", "architecture", "migrate", "migration", "redesign", "root cause"],
    tier: "reasoning",
  },
]

export function tierIndex(tier) {
  const index = TIERS.indexOf(tier)
  return index === -1 ? 2 : index
}

export function tierAt(index) {
  return TIERS[Math.max(0, Math.min(TIERS.length - 1, index))]
}

// Complete <system-reminder>...</system-reminder> blocks are harness plumbing.
// They are near-identical on every turn, so scoring them would pin a whole
// session to one tier.
export function stripReminders(text, markers) {
  const [open, close] = markers
  if (!open || !close) return text
  let out = ""
  let rest = text
  for (;;) {
    const start = rest.toLowerCase().indexOf(open.toLowerCase())
    if (start === -1) break
    const end = rest.toLowerCase().indexOf(close.toLowerCase(), start + open.length)
    if (end === -1) break
    out += rest.slice(0, start)
    rest = rest.slice(end + close.length)
  }
  return (out + rest).trim()
}

const CODE_MARKERS = [
  "```",
  "function",
  "class ",
  "const ",
  "async ",
  "import ",
  "def ",
  "struct ",
  "impl ",
  "trait ",
  "interface ",
  "api",
  "endpoint",
  "database",
  "schema",
  "query",
  "compile",
  "build",
  "stack trace",
  "traceback",
  "exception",
  "panic",
  "segfault",
]

const REASONING_MARKERS = [
  "step by step",
  "think through",
  "think hard",
  "reason about",
  "analyze",
  "analyse",
  "trade-off",
  "tradeoff",
  "design",
  "architect",
  "strategy",
  "root cause",
  "why does",
  "why is",
  "compare",
  "evaluate",
  "prove",
  "derive",
  "figure out",
  "investigate",
  "debug",
]

const TECHNICAL_TERMS = [
  "architecture",
  "distributed",
  "concurrency",
  "concurrent",
  "race condition",
  "deadlock",
  "mutex",
  "atomic",
  "encryption",
  "cryptograph",
  "authentication",
  "authorization",
  "oauth",
  "protocol",
  "throughput",
  "latency",
  "performance",
  "optimiz",
  "memory leak",
  "allocator",
  "kernel",
  "scheduler",
  "migration",
  "refactor",
  "rewrite",
  "transaction",
  "consistency",
  "idempotent",
  "backpressure",
  "shader",
  "gpu",
  "wasm",
  "borrow checker",
  "lifetime",
  "type system",
  "monad",
  "algorithm",
  "complexity",
  "parser",
  "compiler",
  "state machine",
  "invariant",
]

// Conversation and trivia only. Anything that asks for an action on the
// repository - however small - belongs to a work dimension instead, because
// "small" and "cheap to get wrong" are not the same property.
const SIMPLE_INDICATORS = [
  "what is",
  "what are",
  "what does",
  "define",
  "definition of",
  "hi ",
  "hey",
  "hello",
  "thanks",
  "thank you",
  "nice",
  "cool",
  "okay",
  "no worries",
]

// Verbs that mean net-new code, restructuring, or diagnosis. These are the
// turns where a weak model is expensive: it produces something plausible that
// has to be redone on a strong model afterwards.
const BUILD_INTENT = [
  "implement",
  "build a",
  "build the",
  "create a",
  "create the",
  "write a",
  "write the",
  "write tests",
  "test coverage",
  "add support",
  "add a new",
  "refactor",
  "rewrite",
  "redesign",
  "restructure",
  "port ",
  "migrate",
  "optimize",
  "optimise",
  "profile",
  "debug",
  "diagnose",
  "reproduce",
  "design",
  "architect",
  "plan ",
  "why does",
  "why is",
  "why do",
  "figure out",
  "work out",
  "make it work",
  "does not work",
  "doesn't work",
  "not working",
  "broken",
  "fails",
  "failing",
  "flaky",
  "regression",
  "crash",
  "segfault",
  "panic",
  "hangs",
  "deadlock",
  "leak",
]

const MULTI_STEP_PATTERNS = [
  /\bfirst\b[\s\S]{0,200}\bthen\b/i,
  /\bstep\s*\d/i,
  /^\s*\d+[.)]\s+/m,
  /^\s*[-*]\s+[\s\S]*^\s*[-*]\s+/m,
  /\band then\b/i,
  /\bafter (that|which)\b/i,
  /\bfinally\b/i,
]

// Short replies that only make sense as a continuation of the previous turn.
// Scoring them on their own text always lands at the bottom, which is how a
// hard task silently falls off the strong model halfway through.
//
// Approvals and acknowledgements are kept apart because they fail differently.
// An approval authorises work that was just proposed, so getting it wrong means
// a weak model executing a plan it never saw. An acknowledgement asks for
// nothing, so the worst case is a slightly bland reply.
const APPROVAL_PATTERNS = [
  /^(y|yes|yeah|yep|ok|okay|sure|go|next|please|k)\W*$/i,
  /^(yes|ok|okay|sure|please)?\s*(do it|do that|go ahead|carry on|continue|proceed|keep going|carry on|try again|retry|again|fix it|apply it|ship it|lgtm)\W*$/i,
]

const ACKNOWLEDGEMENT_PATTERNS = [
  /^(thanks|thank you|ty|cheers|nice|cool|great|awesome|perfect|beautiful|sweet|neat|got it|understood|makes sense|sounds good|no worries|np)[.!\s]*$/i,
  /^(thanks|thank you)[,!\s]+(that|it)\s+(worked|works|did it|looks good|is good|is right)[.!\s]*$/i,
  /^(that|it)\s+(worked|works|did it|looks good|is good|is right)\W*$/i,
]

function countMatches(haystack, needles) {
  let n = 0
  for (const needle of needles) if (haystack.includes(needle)) n++
  return n
}

function saturate(count, full) {
  if (full <= 0) return 0
  return Math.min(1, count / full)
}

// Any of these means the turn expects work on the repository, which needs tool
// use and a model that can be trusted with it. A short prompt is not the same
// as a cheap one, so the free tier is kept to turns that ask for nothing.
const WORK_VERBS =
  /\b(implement|build|write|create|add|fix|repair|patch|change|edit|update|modify|refactor|rewrite|move|delete|remove|install|configure|set ?up|debug|test|run|check|verify|review|explain|describe|document|find|search|locate|trace|read|open|show|list|compare|why|how|where|which|convert|migrate|generate|make)\b/i

export function wantsWork(ask) {
  return WORK_VERBS.test(ask)
}

/**
 * `"approval"` for a turn that authorises work, `"acknowledgement"` for one
 * that asks for nothing, `undefined` for anything with content of its own.
 */
export function continuationKind(ask) {
  // `opencode run` hands the prompt through with its surrounding quotes intact,
  // and people quote short replies by hand too. Neither changes what the turn is.
  const trimmed = ask.trim().replace(/^["'`]+/, "").replace(/["'`]+$/, "").trim()
  if (!trimmed) return "acknowledgement"
  if (trimmed.length > 40) return undefined
  if (APPROVAL_PATTERNS.some((re) => re.test(trimmed))) return "approval"
  if (ACKNOWLEDGEMENT_PATTERNS.some((re) => re.test(trimmed))) return "acknowledgement"
  return undefined
}

export function retryRequested(ask) {
  return /^(?:(?:it(?:'s| is)|this(?: is)?|that(?: is)?)\s+)?still (?:broken|failing|not working)\W*$/i.test(ask.trim()) ||
    /^(?:please\s+)?(?:try again|retry|again|that didn't (?:work|fix it)|that did not (?:work|fix it))\W*$/i.test(ask.trim())
}

/**
 * Score a single prompt across seven dimensions and map it onto a tier.
 *
 * Returns `{ tier, score, signals }`. `score` is in roughly [-1, 1]; the
 * boundaries in `tierBoundaries` cut it into tiers.
 */
export function score(input) {
  const { ask, system = "", weights, boundaries, tokenThresholds, technicalKeywords = [] } = input

  const text = `${ask}\n${system}`.toLowerCase()
  const askLower = ask.toLowerCase()
  const signals = []

  // Rough token estimate. Good enough to separate a one-liner from an essay.
  const tokens = Math.ceil(ask.trim().split(/\s+/).filter(Boolean).length * 1.3)

  let tokenCount = 0
  if (tokens <= tokenThresholds.simple) {
    // Deliberately asymmetric. A long prompt is strong evidence of a big task;
    // a short one is weak evidence of a small one, because "the scheduler
    // deadlocks under load" is six words.
    tokenCount = -0.4
    signals.push(`short (${tokens} tokens)`)
  } else if (tokens >= tokenThresholds.complex) {
    tokenCount = 1
    signals.push(`long (${tokens} tokens)`)
  } else {
    tokenCount = (tokens - tokenThresholds.simple) / (tokenThresholds.complex - tokenThresholds.simple)
  }

  const codeHits = countMatches(text, CODE_MARKERS)
  const codePresence = saturate(codeHits, 4)
  if (codeHits) signals.push(`code (${codeHits})`)

  // Reasoning markers read the human ask alone. A system prompt that says
  // "always think step by step" must not pin every turn to the top tier.
  const reasoningHits = countMatches(askLower, REASONING_MARKERS)
  const reasoningMarkers = saturate(reasoningHits, 3)
  if (reasoningHits) signals.push(`reasoning (${reasoningHits})`)

  const technicalHits = countMatches(text, TECHNICAL_TERMS) + countMatches(text, technicalKeywords)
  const technicalTerms = saturate(technicalHits, 4)
  if (technicalHits) signals.push(`technical (${technicalHits})`)

  const simpleHits = countMatches(askLower, SIMPLE_INDICATORS)
  const simpleIndicators = -saturate(simpleHits, 2)
  if (simpleHits) signals.push(`simple (${simpleHits})`)

  const buildHits = countMatches(askLower, BUILD_INTENT)
  const buildIntent = saturate(buildHits, 2)
  if (buildHits) signals.push(`build intent (${buildHits})`)

  const multiStepHits = MULTI_STEP_PATTERNS.filter((re) => re.test(ask)).length
  const multiStepPatterns = saturate(multiStepHits, 2)
  if (multiStepHits) signals.push(`multi-step (${multiStepHits})`)

  const questions = (ask.match(/\?/g) || []).length
  const questionComplexity = saturate(Math.max(0, questions - 1), 2)
  if (questions > 1) signals.push(`questions (${questions})`)

  const dimensions = {
    tokenCount,
    codePresence,
    reasoningMarkers,
    technicalTerms,
    simpleIndicators,
    buildIntent,
    multiStepPatterns,
    questionComplexity,
  }

  let total = 0
  for (const [name, value] of Object.entries(dimensions)) total += value * (weights[name] ?? 0)

  let tier
  if (total < boundaries.trivial_simple) tier = "trivial"
  else if (total < boundaries.simple_medium) tier = "simple"
  else if (total < boundaries.medium_complex) tier = "medium"
  else if (total < boundaries.complex_reasoning) tier = "complex"
  else tier = "reasoning"

  // Two or more explicit reasoning markers is an unambiguous request for
  // thinking, whatever the weighted score says.
  if (reasoningHits >= 2 && tier !== "reasoning") {
    tier = "reasoning"
    signals.push("reasoning-marker override")
  }

  return { tier, score: Number(total.toFixed(3)), signals, dimensions, tokens }
}

/**
 * Deterministic keyword rules run ahead of the scorer. When several match, the
 * highest tier wins, so rule order cannot silently change behavior.
 */
export function keywordTier(ask, rules) {
  const lower = ask.toLowerCase()
  let best
  let matched
  for (const rule of rules ?? []) {
    if (!rule?.keywords?.length) continue
    const hit = rule.keywords.find((keyword) => lower.includes(String(keyword).toLowerCase()))
    if (!hit) continue
    if (best === undefined || tierIndex(rule.tier) > tierIndex(best)) {
      best = rule.tier
      matched = hit
    }
  }
  return best ? { tier: best, keyword: matched } : undefined
}

/**
 * Explicit per-prompt overrides. `!simple` / `!medium` / `!complex` /
 * `!reasoning`, plus `!fast` and `!deep` aliases. Returns the tier and the ask
 * with the directive removed, so the directive never reaches the model.
 */
const DIRECTIVES = {
  "!trivial": "trivial",
  "!free": "trivial",
  "!simple": "simple",
  "!fast": "simple",
  "!cheap": "simple",
  "!medium": "medium",
  "!mid": "medium",
  "!complex": "complex",
  "!reasoning": "reasoning",
  "!deep": "reasoning",
  "!hard": "reasoning",
  "!max": "reasoning",
}

export function directiveTier(ask) {
  const match = /(^|\s)(![a-z]+)(?=\s|$)/i.exec(ask)
  if (!match) return undefined
  const tier = DIRECTIVES[match[2].toLowerCase()]
  if (!tier) return undefined
  return { tier, directive: match[2], ask: (ask.slice(0, match.index) + " " + ask.slice(match.index + match[0].length)).trim() }
}
