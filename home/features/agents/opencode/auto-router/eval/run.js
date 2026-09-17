#!/usr/bin/env node
//
// Measures the router's classifier against graded prompts.
//
//   node eval/run.js                          # local model, default settings
//   node eval/run.js --model granite4.2:8b-q8_0
//   node eval/run.js --heuristic              # the offline keyword scorer
//   node eval/run.js --tune                   # search better tier boundaries
//   node eval/run.js --set real|probes|all
//
// The graded set is two files. `gold_real.json` is 150 real turns sampled from
// this machine's own OpenCode history, stratified by length, so the headline
// number reflects the traffic that actually shows up. `gold_probes.json` is 40
// hand-written cases for the corners that real traffic is too thin to measure:
// the reasoning tier, and the biases a judge is known to have - long prompts
// that are easy, short prompts that are hard, code-heavy prompts that are
// trivial.
//
// Both were graded against RUBRIC.md. The number to watch is `adjacent`: a tier
// off by one costs a slightly wrong model, while off by two means a cheap model
// on hard work or the reverse.

import fs from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

import { createClassifier, classifierDefaults } from "../classifier.js"
import { continuationKind, directiveTier, score, TIERS, tierIndex, wantsWork } from "../classify.js"

const HERE = path.dirname(fileURLToPath(import.meta.url))
const ROOT = path.join(HERE, "..")

const argv = process.argv.slice(2)
const flag = (name, fallback) => {
  const index = argv.indexOf(`--${name}`)
  if (index === -1) return fallback
  const next = argv[index + 1]
  return next && !next.startsWith("--") ? next : true
}

const routerConfig = JSON.parse(fs.readFileSync(path.join(ROOT, "auto-router.json"), "utf8"))

const which = flag("set", "all")
const cases = [
  ...(which === "probes" ? [] : JSON.parse(fs.readFileSync(path.join(HERE, "gold_real.json"), "utf8"))),
  ...(which === "real" ? [] : JSON.parse(fs.readFileSync(path.join(HERE, "gold_probes.json"), "utf8"))),
]

const useHeuristic = argv.includes("--heuristic")
const concurrency = Number(flag("concurrency", 4))

function heuristicTier(ask) {
  const scored = score({
    ask,
    weights: routerConfig.weights,
    boundaries: routerConfig.boundaries,
    tokenThresholds: routerConfig.tokenThresholds ?? { simple: 15, complex: 400 },
    technicalKeywords: routerConfig.technicalKeywords ?? [],
  })
  return { tier: scored.tier, difficulty: null, rule: "heuristic", ms: 0 }
}

async function main() {
  let predict
  let label

  if (useHeuristic) {
    label = "heuristic (keyword scorer)"
    predict = async (item) => heuristicTier(item.ask)
  } else {
    const config = {
      ...classifierDefaults(),
      ...(routerConfig.classifier ?? {}),
      enabled: true,
    }
    if (typeof flag("model") === "string") config.model = flag("model")
    if (typeof flag("endpoint") === "string") config.endpoint = flag("endpoint")
    // --thresholds 2.5,4.5,6.5,8.5
    if (typeof flag("thresholds") === "string") {
      const [simple, medium, complex, reasoning] = String(flag("thresholds")).split(",").map(Number)
      config.thresholds = { simple, medium, complex, reasoning }
    }
    // An evaluation run must see every failure rather than quietly falling
    // back, so the breaker never opens but every attempt still logs.
    config.failuresBeforeOpen = 1
    config.breakerMs = 0
    config.maxBreakerMs = 0
    config.timeoutMs = Number(flag("timeout", 60_000))
    label = `${config.model} @ ${config.endpoint}`
    const classifier = createClassifier({
      config,
      log: (level, message, extra) => console.error(`  [${level}] ${message}`, extra ?? ""),
    })
    predict = async (item) => (await classifier.classify(item.ask)) ?? { tier: null, rule: "FAILED", ms: 0 }
  }

  console.log(`\n${label}`)
  console.log(`${cases.length} graded prompts (${which})\n`)

  // The classifier is one stage of the router, not the whole of it, and
  // measuring it alone overstates its errors. A bare "hit it" reaches the model
  // as four characters and is correctly graded as asking for nothing; in the
  // running system it never gets that far, because an approval inherits the
  // tier of the turn it approves before any model is consulted. Evaluating the
  // stages that actually run is the only number that predicts behaviour.
  const gated = predict
  predict = async (item) => {
    const directive = directiveTier(item.ask)
    if (directive) return { tier: directive.tier, rule: "directive", ms: 0 }

    const kind = continuationKind(item.ask)
    if (kind === "acknowledgement") return { tier: "trivial", rule: "acknowledgement", ms: 0 }
    if (kind === "approval") return { tier: routerConfig.continuationFallback ?? "medium", rule: "approval", ms: 0 }

    const out = await gated(item)
    if (!out.tier) return out

    // A turn the model itself calls a continuation inherits the session's tier
    // in the router. There is no session here, so it gets the same fallback the
    // router uses when it resumes a conversation it has no memory of. That is
    // the honest number: it is what the router would do on a cold start.
    if (out.continuation) return { ...out, tier: routerConfig.continuationFallback ?? "medium" }

    // Same floors the router applies after classification.
    if (out.tier === "trivial" && wantsWork(item.ask)) return { ...out, tier: "simple", rule: `${out.rule}+work` }
    return out
  }

  const results = new Array(cases.length)
  let next = 0
  let done = 0
  const workers = Array.from({ length: useHeuristic ? 1 : concurrency }, async () => {
    for (;;) {
      const index = next++
      if (index >= cases.length) return
      const item = cases[index]
      results[index] = { item, out: await predict(item) }
      done += 1
      if (!useHeuristic && done % 20 === 0) process.stderr.write(`  ${done}/${cases.length}\r`)
    }
  })
  await Promise.all(workers)
  process.stderr.write("            \r")

  report(results)

  // Threshold calibration does not need the model. Keeping the raw gradings
  // makes a sweep instant and, more importantly, reproducible: the numbers in
  // README.md can be recomputed from a file instead of from a GPU that has to
  // be up and holding the same weights.
  const dump = flag("dump")
  if (dump) {
    const file = typeof dump === "string" ? dump : path.join(HERE, "gradings.json")
    fs.writeFileSync(
      file,
      JSON.stringify(
        {
          model: label,
          when: new Date().toISOString(),
          gradings: results.map(({ item, out }) => ({
            id: item.id,
            gold: item.tier,
            difficulty: out.difficulty ?? null,
            rule: out.rule ?? null,
            tier: out.tier ?? null,
          })),
        },
        null,
        1,
      ),
    )
    console.log(`\nwrote ${file}`)
  }

  if (argv.includes("--tune") && !useHeuristic) tune(results)
}

function report(results) {
  const confusion = new Map()
  let exact = 0
  let adjacent = 0
  let failed = 0
  let signedTotal = 0
  const latencies = []

  for (const { item, out } of results) {
    if (!out.tier) {
      failed += 1
      continue
    }
    const gap = tierIndex(out.tier) - tierIndex(item.tier)
    signedTotal += gap
    if (gap === 0) exact += 1
    if (Math.abs(gap) <= 1) adjacent += 1
    const key = `${item.tier}>${out.tier}`
    confusion.set(key, (confusion.get(key) ?? 0) + 1)
    if (out.ms) latencies.push(out.ms)
  }

  const graded = results.length - failed
  const pct = (n) => `${((n / graded) * 100).toFixed(1)}%`

  console.log(`exact     ${String(exact).padStart(4)}  ${pct(exact)}`)
  console.log(`adjacent  ${String(adjacent).padStart(4)}  ${pct(adjacent)}`)
  console.log(`off by 2+ ${String(graded - adjacent).padStart(4)}  ${pct(graded - adjacent)}`)
  if (failed) console.log(`failed    ${String(failed).padStart(4)}`)
  console.log(`bias      ${(signedTotal / graded).toFixed(3)} tiers (negative = grades too cheap)`)

  // Mean per-gold-tier routing cost, the same measure the tuner minimises, so a
  // model comparison and a boundary search cannot disagree about what is better.
  const perTier = new Map()
  for (const { item, out } of results) {
    if (!out.tier) continue
    const bucket = perTier.get(item.tier) ?? { cost: 0, n: 0, exact: 0 }
    bucket.cost += tierCost(tierIndex(out.tier), tierIndex(item.tier))
    bucket.exact += tierIndex(out.tier) === tierIndex(item.tier) ? 1 : 0
    bucket.n += 1
    perTier.set(item.tier, bucket)
  }
  let costTotal = 0
  let balanced = 0
  for (const bucket of perTier.values()) {
    costTotal += bucket.cost / bucket.n
    balanced += bucket.exact / bucket.n
  }
  console.log(`cost      ${(costTotal / perTier.size).toFixed(3)} mean per-tier (under-grading weighted ${UNDER_COST}x)`)
  console.log(`balanced  ${((balanced / perTier.size) * 100).toFixed(1)}% exact, averaged over tiers`)

  if (latencies.length) {
    latencies.sort((a, b) => a - b)
    const at = (p) => latencies[Math.min(latencies.length - 1, Math.floor((latencies.length * p) / 100))]
    console.log(`latency   p50 ${at(50)}ms  p90 ${at(90)}ms  p99 ${at(99)}ms`)
  }

  console.log("\n           predicted")
  console.log(`gold       ${TIERS.map((t) => t.slice(0, 6).padStart(7)).join("")}   n`)
  for (const gold of TIERS) {
    const row = TIERS.map((predicted) => String(confusion.get(`${gold}>${predicted}`) ?? "·").padStart(7)).join("")
    const n = TIERS.reduce((sum, p) => sum + (confusion.get(`${gold}>${p}`) ?? 0), 0)
    console.log(`${gold.padEnd(10)} ${row}   ${n}`)
  }

  const worst = results
    .filter(({ item, out }) => out.tier && Math.abs(tierIndex(out.tier) - tierIndex(item.tier)) >= 2)
    .sort((a, b) => Math.abs(tierIndex(b.out.tier) - tierIndex(b.item.tier)) - Math.abs(tierIndex(a.out.tier) - tierIndex(a.item.tier)))

  if (worst.length) {
    console.log(`\nworst misses (${worst.length})`)
    for (const { item, out } of worst.slice(0, 15)) {
      const ask = item.ask.replace(/\s+/g, " ").slice(0, 96)
      console.log(`  ${item.id}  ${item.tier} -> ${out.tier}  [${out.rule ?? "?"} ${out.difficulty ?? ""}]  ${ask}`)
    }
  }
}

// The model's output is a number. Where the tier boundaries sit on that number
// is a separate choice, it is free to change, and it should not be guessed.
//
// The objective is not accuracy. Two things make plain accuracy the wrong
// target here:
//
//   - The tiers are wildly unbalanced (75 medium against 7 trivial), so an
//     accuracy-maximising search buys its score by pushing everything into
//     `medium` and giving up the tails entirely. Averaging the cost per gold
//     tier instead makes the rare tiers count as much as the common one.
//
//   - Missing low and missing high are not equally bad. Routing hard work to a
//     cheap model produces a plausible wrong answer that has to be found and
//     redone, costing the strong model's tokens anyway plus the user's time.
//     Routing easy work to an expensive model just costs money. The search is
//     told that, rather than being allowed to discover a symmetric optimum.
const UNDER_COST = 2.0
const OVER_COST = 1.0

// Every tier has to keep a band it can actually be predicted from. Left alone,
// the search discovers that the cheapest way to avoid ever under-grading is to
// squeeze a tier down to a sliver nothing lands in, and then reports a good
// average while never routing anything to that tier at all. A typo fix graded 3
// out of 9 must come out `simple`, not `medium`, whatever the mean says.
const MIN_BAND = 1.2

function tierCost(predictedIndex, goldIndex) {
  const gap = predictedIndex - goldIndex
  return gap >= 0 ? gap * OVER_COST : -gap * UNDER_COST
}

function macroCost(scored, thresholds) {
  const perTier = new Map()
  for (const { item, out } of scored) {
    const v = out.difficulty
    const index =
      v >= thresholds.reasoning ? 4 : v >= thresholds.complex ? 3 : v >= thresholds.medium ? 2 : v >= thresholds.simple ? 1 : 0
    const bucket = perTier.get(item.tier) ?? { cost: 0, n: 0, exact: 0, adjacent: 0 }
    bucket.cost += tierCost(index, tierIndex(item.tier))
    bucket.n += 1
    if (index === tierIndex(item.tier)) bucket.exact += 1
    if (Math.abs(index - tierIndex(item.tier)) <= 1) bucket.adjacent += 1
    perTier.set(item.tier, bucket)
  }
  let total = 0
  let exact = 0
  let adjacent = 0
  let n = 0
  for (const bucket of perTier.values()) {
    total += bucket.cost / bucket.n
    exact += bucket.exact
    adjacent += bucket.adjacent
    n += bucket.n
  }
  return { cost: total / perTier.size, exact: exact / n, adjacent: adjacent / n }
}

function search(scored) {
  const grid = []
  for (let v = 1.2; v <= 8.9; v += 0.1) grid.push(Number(v.toFixed(1)))

  let best
  for (const simple of grid) {
    for (const medium of grid) {
      if (medium - simple < MIN_BAND) continue
      for (const complex of grid) {
        if (complex - medium < MIN_BAND) continue
        for (const reasoning of grid) {
          if (reasoning - complex < MIN_BAND) continue
          const thresholds = { simple, medium, complex, reasoning }
          const scoreCard = macroCost(scored, thresholds)
          if (!best || scoreCard.cost < best.cost) best = { ...scoreCard, thresholds }
        }
      }
    }
  }
  return best
}

function tune(results) {
  const scored = results.filter(({ out }) => typeof out.difficulty === "number")
  if (!scored.length) return

  // Boundaries fitted and scored on the same prompts flatter themselves, and a
  // flattering number is the one thing this exercise cannot afford. Five folds:
  // fit on four, score on the fifth, report the mean of the held-out scores.
  // That is what the router will do on prompts nobody has graded.
  const folds = 5
  const held = []
  for (let fold = 0; fold < folds; fold++) {
    const train = scored.filter((_, index) => index % folds !== fold)
    const test = scored.filter((_, index) => index % folds === fold)
    if (!train.length || !test.length) continue
    const fitted = search(train)
    held.push(macroCost(test, fitted.thresholds))
  }

  const mean = (key) => held.reduce((sum, entry) => sum + entry[key], 0) / held.length
  console.log(`\nheld out over ${held.length} folds`)
  console.log(
    `  cost ${mean("cost").toFixed(3)}  exact ${(mean("exact") * 100).toFixed(1)}%  adjacent ${(mean("adjacent") * 100).toFixed(1)}%`,
  )

  const best = search(scored)
  console.log("\nbest thresholds over the whole set")
  console.log(`  ${JSON.stringify(best.thresholds)}`)
  console.log(
    `  cost ${best.cost.toFixed(3)}  exact ${(best.exact * 100).toFixed(1)}%  adjacent ${(best.adjacent * 100).toFixed(1)}%`,
  )

  const histogram = new Map()
  for (const { item, out } of scored) {
    const bucket = Math.round(out.difficulty * 2) / 2
    histogram.set(`${item.tier}`, [...(histogram.get(item.tier) ?? []), bucket])
  }
  console.log("\ndifficulty by gold tier (median [min-max])")
  for (const tier of TIERS) {
    const values = (histogram.get(tier) ?? []).sort((a, b) => a - b)
    if (!values.length) continue
    const median = values[Math.floor(values.length / 2)]
    console.log(`  ${tier.padEnd(10)} ${String(median).padStart(5)}  [${values[0]} - ${values[values.length - 1]}]  n=${values.length}`)
  }
}

await main()
