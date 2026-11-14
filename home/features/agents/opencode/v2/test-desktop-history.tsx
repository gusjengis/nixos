import { expect, test } from "bun:test"
import fs from "node:fs/promises"
import path from "node:path"
import { DesktopHistory } from "../src/component/desktop-history"
import { renderLocal, session } from "./fixture/local"
import { tmpdir } from "./fixture/fixture"
import { json } from "./fixture/tui-client"

async function frameUntil(setup: any, predicate: (frame: string) => boolean) {
  const deadline = Date.now() + 3000
  while (Date.now() < deadline) {
    await setup.renderOnce()
    const frame = setup.captureCharFrame()
    if (predicate(frame)) return frame
    await Bun.sleep(10)
  }
  throw new Error("History picker did not reach the expected state")
}

async function environment(mode: string, run: () => Promise<void>) {
  await using directory = await tmpdir()
  const keys = ["PATH", "CONTEXT_ID", "OPENCODE_CONTEXT_SCOPE_FILE", "OPENCODE_CONTEXT_STATE_FILE", "FIXTURE_HISTORY_MODE"]
  const saved = Object.fromEntries(keys.map((key) => [key, process.env[key]]))
  const bin = path.join(directory.path, "bin")
  const state = path.join(directory.path, "state.json")
  const record = { owner: "owner", chat: "ses_portable", availability: "portable_only", freshness: "current_as_known",
    known_revision: "r1", base_revision: "r1", members: {}, operation: { phase: "idle" } }
  await fs.mkdir(bin)
  await fs.writeFile(state, JSON.stringify({ version: 1, generation: 1, conversations: { "owner/ses_portable": record } }))
  const scope = path.join(directory.path, "scope.json")
  await fs.writeFile(scope, JSON.stringify({ context_id: "owner", ids: ["owner"], hidden: [], labels: {} }))
  await fs.writeFile(path.join(bin, "opencode-context-chats"), `#!${process.execPath}
    import fs from "node:fs";
    if (process.env.FIXTURE_HISTORY_MODE === "fail") { console.error("Portable fixture unavailable"); process.exit(1); }
    if (process.argv[2] === "list") console.log(JSON.stringify({summaries:[{owner:"owner",chat:"ses_portable",title:"Portable fixture",state:${JSON.stringify(record)}}]}));
    else if (process.argv[2] === "ensure") {
      const state = JSON.parse(fs.readFileSync(process.env.OPENCODE_CONTEXT_STATE_FILE,"utf8"));
      Object.assign(state.conversations["owner/ses_portable"],{availability:"local",selected_root:"ses_imported",members:{ses_portable:"ses_imported"}});
      state.generation++; fs.writeFileSync(process.env.OPENCODE_CONTEXT_STATE_FILE,JSON.stringify(state));
      console.log(JSON.stringify({session_id:"ses_imported"}));
    }
  `, { mode: 0o700 })
  Object.assign(process.env, { PATH: bin + path.delimiter + (saved.PATH ?? ""), CONTEXT_ID: "owner",
    OPENCODE_CONTEXT_SCOPE_FILE: scope, OPENCODE_CONTEXT_STATE_FILE: state, FIXTURE_HISTORY_MODE: mode })
  try { await run() }
  finally {
    for (const key of keys) {
      if (saved[key] === undefined) delete process.env[key]
      else process.env[key] = saved[key]
    }
  }
}

test("V2 history keeps local conversations usable when portable discovery fails and hides siblings", async () => {
  await environment("fail", async () => {
    const local = { ...session("ses_local"), title: "Local fixture", metadata: { desktop_context: { id: "owner", chat: "ses_local", session: "ses_local" } } }
    const sibling = { ...session("ses_sibling"), title: "Sibling fixture", metadata: { desktop_context: { id: "sibling", chat: "ses_sibling", session: "ses_sibling" } } }
    await using setup = await renderLocal({ sessions: [local, sibling], fetch: async (url) => {
      if (url.pathname === "/api/session") return json({ data: [local, sibling], cursor: {} })
    } })
    setup.dialog.replace(() => <DesktopHistory />)
    const frame = await frameUntil(setup, (frame) => frame.includes("Local fixture") && frame.includes("Portable fixture unavailable"))
    expect(frame).not.toContain("Sibling fixture")
    setup.mockInput.pressEnter()
    const deadline = Date.now() + 2000
    while (setup.route.data.type !== "session" && Date.now() < deadline) await Bun.sleep(10)
    expect(setup.route.data).toMatchObject({ type: "session", sessionID: "ses_local" })
  })
})

test("V2 history imports only the selected portable conversation and verifies it before routing", async () => {
  await environment("portable", async () => {
    const imported = { ...session("ses_imported"), title: "Portable fixture", metadata: {
      desktop_context: { id: "owner", chat: "ses_portable", session: "ses_portable" },
    } }
    await using setup = await renderLocal({ sessions: [imported] })
    setup.dialog.replace(() => <DesktopHistory />)
    await frameUntil(setup, (frame) => frame.includes("Portable fixture"))
    setup.mockInput.pressEnter()
    const deadline = Date.now() + 2000
    while (setup.route.data.type !== "session" && Date.now() < deadline) await Bun.sleep(10)
    expect(setup.route.data).toMatchObject({ type: "session", sessionID: "ses_imported" })
  })
})
