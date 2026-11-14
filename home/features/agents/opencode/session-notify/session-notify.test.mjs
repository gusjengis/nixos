import assert from "node:assert/strict"
import { readFile } from "node:fs/promises"
import * as path from "node:path"
import * as os from "node:os"
import { test } from "node:test"
import { SourceTextModule, SyntheticModule } from "node:vm"

const source = await readFile(new URL("./session-notify.js", import.meta.url), "utf8")

async function fixture({ custom = false, playbackFails = false } = {}) {
  const state = { dnd: "true", audio: [], notifications: [], writes: 0, queries: 0 }
  const dependencies = {
    "node:path": path,
    "node:os": os,
    "node:fs/promises": {
      readFile,
      access: async () => { if (!custom) throw new Error("No custom sound") },
      writeFile: async () => { state.writes++ },
      rm: async () => {},
    },
    "node:child_process": {
      execFile(file, args, options, callback) {
        if (typeof options === "function") callback = options
        if (file === "quickshell") {
          assert.deepEqual(args, ["ipc", "call", "notifications", "dnd"])
          assert.equal(options.timeout, 1000)
          state.queries++
          callback(state.dnd instanceof Error ? state.dnd : null, `${state.dnd}\n`)
        } else {
          callback(new Error("No desktop focus"), "")
        }
      },
      spawn(file, args) {
        state.notifications.push({ file, args })
        return { on() {}, unref() {} }
      },
    },
  }
  const module = new SourceTextModule(source, {
    initializeImportMeta(meta) { meta.dirname = import.meta.dirname },
  })
  await module.link((name) => {
    const exports = dependencies[name]
    return new SyntheticModule(Object.keys(exports), function () {
      for (const [key, value] of Object.entries(exports)) this.setExport(key, value)
    })
  })
  await module.evaluate()
  state.emit = async (type) => {
    // Fresh instance avoids the lifecycle debounce between independent cases.
    const plugin = await module.namespace.SessionNotifyPlugin({
      directory: "/test/project",
      $: async (strings, ...values) => {
        state.audio.push({ command: strings.join(""), values })
        if (playbackFails) throw new Error("Audio unavailable")
      },
    })
    await plugin.event({ event: { type, properties: { sessionID: "session", id: "question" } } })
  }
  return state
}

for (const type of ["session.idle", "session.error", "question.asked"]) {
  for (const custom of [false, true]) {
    test(`${type}: DND mutes ${custom ? "custom" : "generated"} audio and resumes live`, async () => {
      const state = await fixture({ custom })
      await state.emit(type)
      assert.equal(state.queries, 1)
      assert.equal(state.notifications.length, 1)
      assert.equal(state.writes, 0)
      assert.deepEqual(state.audio, [])
      state.dnd = "false"
      await state.emit(type)
      assert.equal(state.queries, 2)
      assert.equal(state.audio.length, 1)
      assert.equal(state.audio[0].command, "pw-play ")
    })
  }
}

test("DND suppresses bell fallback; unavailable DND endpoint preserves audio fallback", async () => {
  const state = await fixture({ playbackFails: true })
  await state.emit("session.idle")
  assert.deepEqual(state.audio, [])
  state.dnd = new Error("DND endpoint unavailable")
  await state.emit("session.idle")
  assert.deepEqual(state.audio.map(item => item.command), ["pw-play ", "bash -lc "])
})
