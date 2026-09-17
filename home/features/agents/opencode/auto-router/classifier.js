// Local LLM prompt classifier for the Auto model router.
//
// Sends the user's turn to a small model held resident on the fleet's GPU box
// and gets back a graded difficulty. The keyword scorer in classify.js stays as
// the fallback for when that box is unreachable, which on a laptop away from
// the tailnet is most of the time.
//
// Design follows the published work on LLM routing rather than inventing one:
//
//   - The model emits a *difficulty number*, not a tier name. Tier boundaries
//     live in auto-router.json and are applied here, so recalibrating the
//     router costs an edit rather than a different model. NVIDIA's NeMo
//     Switchyard does the same thing with its `p_solve` forecast, and RouteLLM
//     is mathematically the same shape (a win probability plus a threshold).
//     https://github.com/NVIDIA-NeMo/Switchyard
//     https://arxiv.org/abs/2406.18665
//
//   - The model must name a *rule* from a fixed list before it emits the
//     number. This is chain-of-thought with no free text in it: it costs four
//     tokens instead of two hundred, it constrains the decision, and it makes
//     every routing decision auditable after the fact. Switchyard's
//     capability-classifier prompt uses the same shape.
//
//   - The difficulty digit is scored from its *logprobs*, not from the token
//     the sampler happened to pick. A single greedy digit from a 4B model
//     clusters hard on a few values and ties constantly; the probability-
//     weighted expectation over all nine digits is smooth, which is what makes
//     tunable boundaries meaningful. This is G-Eval's method.
//     https://arxiv.org/abs/2303.16634
//
//   - Output is constrained by a JSON schema server-side, and the schema is
//     also described in the prompt, which is the combination that avoids the
//     measured quality loss from structured decoding.
//     https://blog.dottxt.co/say-what-you-mean.html
//
// The rubric below is the prose in RUBRIC.md compiled down. Change one and
// change the other, or the evaluation set stops measuring the thing that runs.

import { TIERS } from "./classify.js"

// Named rules the model has to choose between before it grades anything.
//
// Deliberately not ordered or numbered. An ordinal id ("L1".."L5") invites the
// model to infer the tier boundary from the id itself and then grade to match
// it, which turns the number back into a label.
// Each rule carries the difficulty band it usually lands in.
//
// Without the bands the model answers almost entirely in 3s and 7s: it snaps to
// whichever rule it picked and grades from the rule's own wording, leaving the
// middle of the scale empty and half of the routine work misfiled as either
// mechanical or hard. Naming the band turns the digit into a small adjustment
// on a decision that has already been made, which is the part a 4B model is
// actually reliable at.
//
// The bands are ordered, and that ordering is the real classifier. Measured
// against the graded set, the rule alone predicts the tier better than the
// digit does.
export const RULES = [
  { id: "no_work", band: "1", text: "Asks for nothing: a greeting, thanks, an acknowledgement, or a remark." },
  {
    id: "continuation",
    band: "grade the work it authorises",
    text: "Cannot be understood on its own. It approves, corrects, or adds information to work already under discussion: \"hit it\", \"still doing it\", \"my bad, go ahead\", \"let's try option B\", \"new info: <output>\".",
  },
  {
    id: "direct_answer",
    band: "2",
    text: "A question answerable in a line or two from a named file, a stated error, or general knowledge.",
  },
  {
    id: "mechanical_edit",
    band: "2-3",
    text: "One obvious edit with no judgement in it: a typo, a rename, a comment, a formatting change, a version bump.",
  },
  {
    id: "run_command",
    band: "3",
    text: "Run, check or inspect something and report what it says. No design, no edit.",
  },
  {
    id: "stated_fix",
    band: "3",
    text: "A defect where the turn already points at the cause: an error message, compiler diagnostic, stack trace or log that names a file, line, symbol or missing value.",
  },
  { id: "explain_code", band: "4-5", text: "Explain, summarise or review existing code or configuration." },
  {
    id: "pattern_feature",
    band: "4-5",
    text: "A small feature or change that copies a pattern already present in the codebase.",
  },
  {
    id: "research_gather",
    band: "4-5",
    text: "Go out and find, compare, or collect things. Each step is easy; there are many of them.",
  },
  {
    id: "multi_file_change",
    band: "5",
    text: "A coordinated change across several files where the approach is clear.",
  },
  { id: "new_component", band: "6", text: "A new module, service, screen or subsystem that does not exist yet." },
  {
    id: "unfamiliar_integration",
    band: "7",
    text: "Work against an API, protocol or platform whose behaviour has to be discovered.",
  },
  {
    id: "unknown_cause",
    band: "6-7",
    text: "Something misbehaves and nothing in the turn points at where. There is no error text, or the error does not name the thing at fault.",
  },
  {
    id: "ambiguous_requirements",
    band: "6-7",
    text: "The turn can be read more than one reasonable way and nothing in it decides which.",
  },
  {
    id: "open_ended_design",
    band: "7-8",
    text: "The shape of the answer is not given. An architecture or a policy has to be invented.",
  },
  {
    id: "intermittent_defect",
    band: "8-9",
    text: "A failure that is timing dependent, environment dependent, or cannot be reproduced on demand.",
  },
  {
    id: "correctness_critical",
    band: "8-9",
    text: "Concurrency, security, authentication, data migration, deletion, or measured performance work. A plausible wrong answer is expensive.",
  },
  { id: "other", band: "5", text: "None of the above fits." },
]

export const DIFFICULTY_DIGITS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]

export const SCHEMA = {
  type: "object",
  properties: {
    rule: { type: "string", enum: RULES.map((rule) => rule.id) },
    difficulty: { type: "string", enum: DIFFICULTY_DIGITS },
  },
  required: ["rule", "difficulty"],
  additionalProperties: false,
}

// Worked examples in exactly the output format. Structured decoding is only
// free of quality cost when the prompt shows the same shape the grammar will
// force, and these double as the calibration anchors for the 1-9 scale.
const SHOTS = [
  { ask: "thanks, that worked", rule: "no_work", difficulty: "1" },
  { ask: "hit it", rule: "continuation", difficulty: "5" },
  { ask: "please clean up the warnings", rule: "mechanical_edit", difficulty: "3" },
  {
    ask: "rehome\nerror: … while evaluating a branch condition\n         at /nix/store/rcmh3p-source/lib/modules.nix:331:9:\n         error: attribute 'hyprland' missing",
    rule: "stated_fix",
    difficulty: "3",
  },
  {
    ask: "make the ring rendering dim all parts of the ring that have already passed today",
    rule: "pattern_feature",
    difficulty: "5",
  },
  {
    ask: "three things: bump the opencode pin to v1.18.30, drop the vial module from t480s, and add commit-mono to the font list",
    rule: "multi_file_change",
    difficulty: "5",
  },
  {
    ask: "I want to run rehome every time my computer boots, the first time it connects to the network",
    rule: "new_component",
    difficulty: "7",
  },
  { ask: "the scheduler deadlocks under load, find out why", rule: "correctness_critical", difficulty: "9" },
]

const SYSTEM = `You grade how hard a task is for a coding agent. You never do the task.

The agent you are grading for is competent but not the strongest model available. It has full tool access to the repository and gets one attempt. Grade how likely it is to finish the turn correctly without a stronger model having to redo the work. Hard means unlikely.

Step 1. Pick exactly one rule id, the one that describes the hardest requirement in the turn. The number after each rule is where that kind of turn usually lands.
${RULES.map((rule) => `- ${rule.id} (${rule.band}): ${rule.text}`).join("\n")}

Pick continuation only when the turn genuinely makes no sense alone. A turn that states its own task is not a continuation, however short.

Step 2. Give a difficulty from 1 to 9. Start from the rule's usual band and move within it, or one step outside it, if the specifics of this turn warrant it. For a continuation, grade the work it appears to be authorising or reporting on, not the length of the reply.
1-2  asks for nothing, or a one-line answer
3-4  one mechanical action, location known, no judgement
5-6  routine work with a clear approach, even when it touches several files
7-8  a decision that has not been made yet, or a cause that has to be found first
9    correctness critical, ambiguous, or open ended; a plausible wrong answer is expensive

How to grade:
- Grade the hardest requirement in the turn, not the average one.
- Length is not difficulty. Pasted logs, stack traces and file dumps make a prompt long, not hard.
- Being specific makes a task easier. A prompt that names the files, states the wanted behaviour and gives a way to verify it is easier than a vague one. A short prompt can be the hardest kind.
- Being about code is not difficulty. Most coding turns are 3 to 6.
- Touching many files is not by itself hard. If the change is the same kind of edit in each place, or the turn says what to do in each place, it stays a 5 or a 6. What makes a turn a 7 is that somebody still has to decide something.
- A cause that is already stated is easy. A cause that has to be found is hard. A cause that only appears sometimes is harder.
- A pasted error message, stack trace or compiler diagnostic is a stated cause, not an unknown one, however long or unfamiliar it looks. Reading an error and fixing what it names is a 3 or a 4.
- Running commands and reporting what they say is easy even when there are several of them.
- "sometimes", "occasionally", "every so often", "can't reproduce it", "it's unreliable" mean intermittent_defect, not unknown_cause. A fault that will not hold still is the hardest kind there is.
- Deleting, overwriting, or rewriting anything that cannot be got back is correctness_critical even when the method is obvious. Getting it wrong is not recoverable by trying again.
- If the turn can be read two reasonable ways and nothing decides between them, that is hard.
- Deleting data, changing authentication, editing a migration, or touching something every machine depends on adds one.
- Tone is not difficulty. Frustration does not make a task hard and politeness does not make it easy.
- Do not default to the middle. Commit to a number.

Answer with JSON only: {"rule": "<rule id>", "difficulty": "<1-9>"}`

function buildMessages(ask, meta) {
  const messages = [{ role: "system", content: SYSTEM }]
  for (const shot of SHOTS) {
    messages.push({ role: "user", content: `<turn>\n${shot.ask}\n</turn>` })
    messages.push({ role: "assistant", content: JSON.stringify({ rule: shot.rule, difficulty: shot.difficulty }) })
  }
  const notes = []
  if (meta?.attachments) notes.push(`${meta.attachments} file(s) attached`)
  const suffix = notes.length ? `\n<context>${notes.join(", ")}</context>` : ""
  messages.push({ role: "user", content: `<turn>\n${ask}\n</turn>${suffix}` })
  return messages
}

/**
 * Keep the ends of a long turn and drop the middle.
 *
 * What a turn is asking for is almost always in its first or last few lines.
 * The middle of a long one is pasted output, and feeding it costs prefill time
 * while actively misleading the grader, because volume reads as difficulty.
 */
export function truncate(ask, { head, tail }) {
  if (ask.length <= head + tail) return { text: ask, truncated: false }
  const dropped = ask.length - head - tail
  return {
    text: `${ask.slice(0, head)}\n\n[... ${dropped} characters omitted ...]\n\n${ask.slice(-tail)}`,
    truncated: true,
  }
}

/**
 * Probability-weighted expectation over the difficulty digit.
 *
 * Ollama returns one entry per generated token. The difficulty digit is the
 * last single-digit token the grammar can emit, so the last match is it. Taking
 * the expectation over the alternatives the model also considered turns a
 * coarse 1-9 label into a continuous value, which is what makes the tier
 * boundaries tunable rather than cosmetic.
 */
export function expectedDifficulty(logprobs, fallback) {
  if (!Array.isArray(logprobs)) return { value: fallback, calibrated: false }

  let chosen
  for (const entry of logprobs) {
    if (typeof entry?.token === "string" && /^[1-9]$/.test(entry.token)) chosen = entry
  }
  const alternatives = chosen?.top_logprobs
  if (!Array.isArray(alternatives) || alternatives.length === 0) {
    const value = chosen ? Number(chosen.token) : fallback
    return { value, calibrated: false }
  }

  let mass = 0
  let weighted = 0
  const distribution = {}
  for (const alternative of alternatives) {
    if (typeof alternative?.token !== "string" || !/^[1-9]$/.test(alternative.token)) continue
    if (typeof alternative.logprob !== "number") continue
    const probability = Math.exp(alternative.logprob)
    mass += probability
    weighted += probability * Number(alternative.token)
    distribution[alternative.token] = Number(probability.toFixed(4))
  }
  if (mass <= 0) return { value: chosen ? Number(chosen.token) : fallback, calibrated: false }

  return { value: weighted / mass, calibrated: true, distribution, mass: Number(mass.toFixed(3)) }
}

/**
 * Map a 1-9 difficulty onto a tier. `thresholds` holds the lower bound of every
 * tier above `trivial`, so four numbers cut the scale into five.
 */
export function difficultyTier(value, thresholds) {
  let tier = TIERS[0]
  for (let index = 1; index < TIERS.length; index++) {
    const bound = thresholds?.[TIERS[index]]
    if (typeof bound === "number" && value >= bound) tier = TIERS[index]
  }
  return tier
}

const DEFAULTS = {
  enabled: true,
  endpoint: "http://omega:11434",
  model: "qwen3:4b-instruct-2507-q8_0",
  // A miss costs the difference between two models on one turn. A stall costs
  // the user staring at an idle terminal, so the budget is tight and the
  // heuristic takes over the moment it is exceeded. Measured p99 on the
  // configured model is under 1.4s, so this is roughly double the worst
  // observed case and well short of being noticed.
  timeoutMs: 3000,
  numCtx: 8192,
  // Enough for {"rule":"unfamiliar_integration","difficulty":"7"} and nothing else.
  numPredict: 32,
  topLogprobs: 10,
  // Ends of a long turn to keep, in characters. Roughly 750 and 375 tokens.
  headChars: 3000,
  tailChars: 1500,
  // Lower bound of each tier on the 1-9 scale. Every rule's band sits wholly
  // inside one tier, so these are the midpoints between bands rather than
  // numbers fitted to a sample: `mechanical_edit` (2-3) is `simple` whatever
  // the graded set happens to contain, and that stability is the point.
  thresholds: { simple: 1.5, medium: 3.5, complex: 5.5, reasoning: 8.0 },
  // Consecutive failures before the endpoint is left alone. One dropped packet
  // should not disable the classifier; a machine that is off should not be
  // dialled on every keystroke.
  failuresBeforeOpen: 2,
  breakerMs: 30_000,
  maxBreakerMs: 600_000,
  cacheSize: 256,
}

export function classifierDefaults() {
  return structuredClone(DEFAULTS)
}

/**
 * @param {object} options
 * @param {object} options.config `classifier` block from auto-router.json.
 * @param {(level: string, message: string, extra?: object) => void} [options.log]
 * @param {typeof fetch} [options.fetch]
 */
export function createClassifier({ config: overrides, log = () => {}, fetch: fetcher = fetch }) {
  const config = { ...DEFAULTS, ...(overrides ?? {}), thresholds: { ...DEFAULTS.thresholds, ...(overrides?.thresholds ?? {}) } }
  if (!config.enabled) return undefined

  const cache = new Map()
  let failures = 0
  let openUntil = 0
  let penalty = config.breakerMs

  const url = `${config.endpoint.replace(/\/+$/, "")}/api/chat`

  const succeed = () => {
    failures = 0
    penalty = config.breakerMs
    openUntil = 0
  }

  // Back off geometrically. The common case for an unreachable endpoint is a
  // laptop off the tailnet for hours, and probing it every turn adds the whole
  // connect timeout to every prompt for nothing.
  const fail = (reason) => {
    failures += 1
    if (failures < config.failuresBeforeOpen) return
    openUntil = Date.now() + penalty
    log("warn", "classifier unreachable, falling back to the heuristic", {
      reason,
      quietForSeconds: Math.round(penalty / 1000),
    })
    penalty = Math.min(penalty * 2, config.maxBreakerMs)
  }

  const classify = async (ask, meta = {}) => {
    if (!ask?.trim()) return undefined
    if (Date.now() < openUntil) return undefined

    const key = `${ask}\u0000${meta.attachments ?? 0}`
    const hit = cache.get(key)
    if (hit) return { ...hit, cached: true }

    const { text, truncated } = truncate(ask, { head: config.headChars, tail: config.tailChars })
    const started = Date.now()

    let payload
    try {
      const response = await fetcher(url, {
        method: "POST",
        headers: { "content-type": "application/json" },
        signal: AbortSignal.timeout(config.timeoutMs),
        body: JSON.stringify({
          model: config.model,
          stream: false,
          // The server is configured to hold this model forever, but a request
          // that arrives after a restart would otherwise reload it on the
          // default idle timer and pay the load again later.
          keep_alive: -1,
          logprobs: true,
          top_logprobs: config.topLogprobs,
          format: SCHEMA,
          messages: buildMessages(text, meta),
          options: {
            temperature: 0,
            seed: 0,
            num_ctx: config.numCtx,
            num_predict: config.numPredict,
          },
        }),
      })
      if (!response.ok) {
        fail(`http ${response.status}`)
        return undefined
      }
      payload = await response.json()
    } catch (error) {
      fail(error?.name === "TimeoutError" ? `timeout after ${config.timeoutMs}ms` : String(error?.message ?? error))
      return undefined
    }

    let verdict
    try {
      verdict = JSON.parse(payload?.message?.content ?? "")
    } catch {
      // A 200 with unparseable content is the documented failure mode of
      // constrained decoding going wrong, and it is not a transport fault, so
      // it must not trip the breaker. One heuristic turn is the right cost.
      log("warn", "classifier returned unparseable content", {
        content: String(payload?.message?.content ?? "").slice(0, 200),
      })
      return undefined
    }

    const digit = Number(verdict?.difficulty)
    if (!Number.isFinite(digit) || digit < 1 || digit > 9) {
      log("warn", "classifier returned no usable difficulty", { verdict })
      return undefined
    }

    succeed()

    const expectation = expectedDifficulty(payload?.logprobs, digit)
    // Round before deciding, not after. Reporting 8 and routing as though it
    // were 7.996 makes the logged number unable to explain the decision it
    // caused, which is exactly the thing that erodes trust in a router.
    const difficulty = Number(expectation.value.toFixed(2))
    const rule = typeof verdict?.rule === "string" ? verdict.rule : undefined
    const result = {
      tier: difficultyTier(difficulty, config.thresholds),
      difficulty,
      emitted: digit,
      rule,
      // A turn that only makes sense as a reply to the previous one carries no
      // difficulty of its own. Its own text grades as trivial every time, which
      // is how a hard task silently falls off the strong model on the word
      // "yes". The caller inherits the session's tier instead.
      continuation: rule === "continuation",
      calibrated: expectation.calibrated,
      distribution: expectation.distribution,
      truncated,
      ms: Date.now() - started,
      model: config.model,
    }

    cache.set(key, result)
    if (cache.size > config.cacheSize) cache.delete(cache.keys().next().value)
    return result
  }

  return {
    classify,
    config,
    get open() {
      return Date.now() < openUntil
    },
  }
}
