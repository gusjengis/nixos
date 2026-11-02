import assert from "node:assert/strict"
import { test } from "node:test"
import { mkdtemp, mkdir, rm } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, dirname } from "node:path"
import { fileURLToPath } from "node:url"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { createHistoryClient } from "./history-client.mjs"

const exec = promisify(execFile)
const here = dirname(fileURLToPath(import.meta.url))
const backend = join(here, "../../desktop/contexts/context_chat_library.py")

test("real CLI summaries/state feed UI; received head refreshes without importing transcript", async (t) => {
  const root = await mkdtemp(join(tmpdir(), "history-backend-"))
  t.after(() => rm(root, { recursive: true, force: true }))
  await mkdir(join(root, "home"))
  const env = { ...process.env, HOME: join(root, "home"), CONTEXT_ROOT: join(root, "contexts"),
    XDG_STATE_HOME: join(root, "state"), XDG_DATA_HOME: join(root, "data"), XDG_CONFIG_HOME: join(root, "config"),
    OPENCODE_DB: join(root, "fixture.db"), OPENCODE_CONTEXT_STATE_FILE: join(root, "conversation-state.json"),
    OPENCODE_CONTEXT_SCOPE_FILE: join(root, "scope.json"), PYTHONDONTWRITEBYTECODE: "1" }
  delete env.CONTEXT_ID
  const fixture = join(here, "history-test-fixture.py")
  const init = JSON.parse((await exec("python3", [fixture, "init"], { env })).stdout)
  env.CONTEXT_ID = init.owner
  const client = createHistoryClient({ env, command: async (args, options = {}) => {
    const { stdout } = await exec("python3", [backend, ...args], { env, signal: options.signal })
    return JSON.parse(stdout)
  } })
  const listed = await client.list()
  assert.equal(listed.summaries.length, 2)
  const remote = listed.summaries.find((row) => row.chat === "ses_remote")
  assert.equal(remote.title, "Portable fixture")
  assert.equal(remote.availability, "portable_only")
  assert.equal(remote.source_device, "fixture-device")
  const local = listed.summaries.find((row) => row.chat === "ses_local")
  assert.equal(await client.open(local, () => {}), "ses_local")
  let arrived
  const updated = new Promise((resolve) => { arrived = resolve })
  const stop = client.observe((_snapshot, meta) => { if (meta.changedHeads?.length) arrived() })
  t.after(stop)
  await exec("python3", [fixture, "update"], { env })
  let timer
  await Promise.race([updated, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Received head was not observed")), 1500) })]).finally(() => clearTimeout(timer))
  const refreshed = await client.list()
  assert.equal(refreshed.summaries.find((row) => row.chat === "ses_remote").title, "Arrived update")
  assert.equal(refreshed.summaries.find((row) => row.chat === "ses_remote").nativeID, null)
})
