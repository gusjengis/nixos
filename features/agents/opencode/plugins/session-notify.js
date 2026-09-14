import { basename, join } from "node:path"
import { tmpdir } from "node:os"
import { access, readFile, writeFile, rm } from "node:fs/promises"
import { execFile, spawn } from "node:child_process"

const CUSTOM_SOUND_FILE = join(
  import.meta.dirname,
  "session-notify.wav",
)

// A question chime must never be mistaken for the finished chime, so it only
// uses a dedicated file and otherwise falls back to its own generated tone.
function customSoundCandidates(kind) {
  if (kind === "ask") {
    return [join(import.meta.dirname, "session-notify-ask.wav")]
  }

  return [join(import.meta.dirname, `session-notify-${kind}.wav`), CUSTOM_SOUND_FILE]
}

function hashString(value) {
  let hash = 2166136261

  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }

  return hash >>> 0
}

function tonesForDirectory(directory, kind) {
  const seed = hashString(directory)
  const roots = [220, 246.94, 261.63, 293.66, 329.63, 392, 440, 493.88]
  const brightPatterns = [
    [0, 4],
    [0, 7],
    [0, 4, 7],
    [0, 7, 12],
    [0, 2, 7],
  ]
  const darkPatterns = [
    [0, -3],
    [0, -5],
    [0, -3, -7],
    [0, -5, -12],
    [0, -2, -7],
  ]

  // Questions get a rising, higher, quicker figure so "needs input" is audibly
  // different from "finished" even though both share the directory's root note.
  const askPatterns = [
    [12, 16, 19],
    [12, 19, 24],
    [12, 17, 24],
    [12, 14, 19],
    [12, 16, 24],
  ]

  const root = roots[seed % roots.length]
  const patternPool = kind === "error"
    ? darkPatterns
    : kind === "ask"
      ? askPatterns
      : brightPatterns
  const pattern = patternPool[(seed >>> 3) % patternPool.length]
  const baseDurationMs = kind === "error"
    ? 135 + ((seed >>> 7) % 45)
    : kind === "ask"
      ? 70 + ((seed >>> 7) % 30)
      : 95 + ((seed >>> 7) % 55)
  const strideMs = kind === "error" ? 34 : kind === "ask" ? -10 : 22

  return pattern.map((semitones, index) => ({
    frequency: Number((root * (2 ** (semitones / 12))).toFixed(2)),
    durationMs: baseDurationMs + index * strideMs,
  }))
}

function createPcm16Wav(tones) {
  const sampleRate = 44100
  const gapMs = 40
  const amplitude = 0.22
  const samples = []

  for (const [index, tone] of tones.entries()) {
    const toneSamples = Math.max(1, Math.floor(sampleRate * tone.durationMs / 1000))

    for (let i = 0; i < toneSamples; i += 1) {
      const t = i / sampleRate
      const envelope = Math.sin(Math.PI * i / toneSamples)
      samples.push(Math.sin(2 * Math.PI * tone.frequency * t) * amplitude * envelope)
    }

    if (index < tones.length - 1) {
      const gapSamples = Math.floor(sampleRate * gapMs / 1000)
      for (let i = 0; i < gapSamples; i += 1) {
        samples.push(0)
      }
    }
  }

  const dataSize = samples.length * 2
  const buffer = Buffer.alloc(44 + dataSize)

  buffer.write("RIFF", 0)
  buffer.writeUInt32LE(36 + dataSize, 4)
  buffer.write("WAVE", 8)
  buffer.write("fmt ", 12)
  buffer.writeUInt32LE(16, 16)
  buffer.writeUInt16LE(1, 20)
  buffer.writeUInt16LE(1, 22)
  buffer.writeUInt32LE(sampleRate, 24)
  buffer.writeUInt32LE(sampleRate * 2, 28)
  buffer.writeUInt16LE(2, 32)
  buffer.writeUInt16LE(16, 34)
  buffer.write("data", 36)
  buffer.writeUInt32LE(dataSize, 40)

  for (let i = 0; i < samples.length; i += 1) {
    const value = Math.max(-1, Math.min(1, samples[i]))
    buffer.writeInt16LE(Math.round(value * 32767), 44 + i * 2)
  }

  return buffer
}

async function playChime($, directory, kind) {
  const tones = tonesForDirectory(directory, kind)

  const soundFile = join(tmpdir(), `opencode-${kind}.wav`)

  for (const candidate of customSoundCandidates(kind)) {
    try {
      await access(candidate)
    } catch {
      // Fall back to the generated tone when no custom file exists.
      continue
    }

    try {
      await $`pw-play ${candidate}`
      return
    } catch {
      // Fall through to the generated tone if the custom file cannot play.
    }
  }

  try {
    await writeFile(soundFile, createPcm16Wav(tones))
    await $`pw-play ${soundFile}`
    return
  } catch {
    try {
      await $`bash -lc ${"printf '\\a'"}`
    } catch {
      // Ignore notification sound failures.
    }
  } finally {
    await rm(soundFile, { force: true }).catch(() => {})
  }
}

function execFileText(file, args, options) {
  return new Promise((resolve, reject) => {
    execFile(file, args, options, (error, stdout) => {
      if (error) {
        reject(error)
        return
      }

      resolve(stdout.trim())
    })
  })
}

async function captureTmuxOrigin(pane) {
  const origin = { pane: pane || "", sessionID: "", sessionName: "", client: "" }
  if (!pane) {
    return origin
  }

  try {
    const output = await execFileText("tmux", [
      "display-message",
      "-p",
      "-t",
      pane,
      "#{session_id}\t#{session_name}\t#{client_name}",
    ])
    const [sessionID = "", sessionName = "", client = ""] = output.split("\t")
    return { ...origin, sessionID, sessionName, client }
  } catch {
    return origin
  }
}

async function processStartTime() {
  try {
    const stat = await readFile(`/proc/${process.pid}/stat`, "utf8")
    return stat.slice(stat.lastIndexOf(")") + 2).split(" ")[19] || ""
  } catch {
    return ""
  }
}

function sendDesktopNotification(title, body, urgency, context) {
  const notifier = spawn("opencode-session-notify", [
    title,
    body,
    urgency,
    context.directory,
    context.sessionID || "",
    context.tmux.pane,
    context.tmux.sessionID,
    context.tmux.sessionName,
    context.tmux.client,
    String(process.pid),
    context.processStartTime,
  ], {
    detached: true,
    stdio: "ignore",
  })
  notifier.on("error", () => {})
  notifier.unref()
}

function questionSummary(questions) {
  if (!Array.isArray(questions) || questions.length === 0) {
    return "waiting for your answer"
  }

  const first = questions[0]
  const label = first?.header || first?.question || "waiting for your answer"

  return questions.length > 1 ? `${label} (+${questions.length - 1} more)` : label
}

export const SessionNotifyPlugin = async ({ $, directory }) => {
  const tmux = await captureTmuxOrigin(process.env.TMUX_PANE)
  const startedAt = await processStartTime()
  let lastNotificationAt = 0
  const childSessions = new Set()
  const interruptedSessions = new Set()
  const sessionTitles = new Map()
  // OpenCode re-emits question.asked while a request stays open, so alert once
  // per request id and clear it when the question is answered or rejected.
  // Values are timestamps so a request that never reports a reply cannot
  // silence the finished chime forever.
  const pendingQuestions = new Map()
  const PENDING_QUESTION_TTL_MS = 10 * 60 * 1000

  return {
    event: async ({ event }) => {
      const projectName = basename(directory)
      const notificationContext = (sessionID) => {
        const title = sessionTitles.get(sessionID)
        return title ? `${projectName}: ${title}` : projectName
      }

      if (event.type === "session.created" || event.type === "session.updated") {
        sessionTitles.set(event.properties.info.id, event.properties.info.title)
        if (event.properties.info.parentID) {
          childSessions.add(event.properties.info.id)
        } else {
          childSessions.delete(event.properties.info.id)
        }
        return
      }

      if (event.type === "session.deleted") {
        childSessions.delete(event.properties.info.id)
        interruptedSessions.delete(event.properties.info.id)
        sessionTitles.delete(event.properties.info.id)
        return
      }

      if (
        event.type === "message.updated"
        && event.properties.info.role === "assistant"
        && event.properties.info.error?.name === "MessageAbortedError"
      ) {
        interruptedSessions.add(event.properties.info.sessionID)
        return
      }

      if (event.type === "question.replied" || event.type === "question.rejected") {
        pendingQuestions.delete(event.properties.requestID)
        return
      }

      if (event.type === "question.asked") {
        const requestID = event.properties.id
        if (pendingQuestions.has(requestID)) {
          return
        }
        pendingQuestions.set(requestID, Date.now())
        lastNotificationAt = Date.now()

        await sendDesktopNotification(
          "OpenCode needs input",
          `${notificationContext(event.properties.sessionID)}: ${questionSummary(event.properties.questions)}`,
          "critical",
          { directory, sessionID: event.properties.sessionID, tmux, processStartTime: startedAt },
        )
        await playChime($, directory, "ask")
        return
      }

      if (event.type !== "session.idle" && event.type !== "session.error") {
        return
      }

      if (event.type === "session.error" && event.properties.error?.name === "MessageAbortedError") {
        if (event.properties.sessionID) {
          interruptedSessions.add(event.properties.sessionID)
        }
        return
      }

      if (childSessions.has(event.properties.sessionID)) {
        return
      }

      // A manual interrupt emits session.error followed by session.idle.
      if (event.type === "session.idle" && interruptedSessions.delete(event.properties.sessionID)) {
        return
      }

      const staleBefore = Date.now() - PENDING_QUESTION_TTL_MS
      for (const [requestID, askedAt] of pendingQuestions) {
        if (askedAt < staleBefore) {
          pendingQuestions.delete(requestID)
        }
      }

      // A pending question already alerted; idle on top of it would just repeat.
      if (event.type === "session.idle" && pendingQuestions.size > 0) {
        return
      }

      const now = Date.now()
      if (now - lastNotificationAt < 1500) {
        return
      }
      lastNotificationAt = now

      if (event.type === "session.error") {
        await sendDesktopNotification(
          "OpenCode error",
          `${notificationContext(event.properties.sessionID)}: session failed`,
          "critical",
          { directory, sessionID: event.properties.sessionID, tmux, processStartTime: startedAt },
        )
        await playChime($, directory, "error")
        return
      }

      await sendDesktopNotification(
        "OpenCode finished",
        notificationContext(event.properties.sessionID),
        "normal",
        { directory, sessionID: event.properties.sessionID, tmux, processStartTime: startedAt },
      )
      await playChime($, directory, "done")
    },
  }
}
