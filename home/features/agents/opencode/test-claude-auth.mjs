// Run: CLAUDE_AUTH_PLUGIN=/nix/store/.../opencode-claude-auth.js node --test test-claude-auth.mjs
import assert from "node:assert/strict"
import { execFile } from "node:child_process"
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { promisify } from "node:util"
import { test } from "node:test"

const run = promisify(execFile)
const fixture = fileURLToPath(new URL("./claude-auth-fixture.mjs", import.meta.url))
const cases = ["valid", "expired", "cli-fallback", "idle-expired", "expiry", "rotate",
  "rotate-401", "rotate-429", "refresh-switch", "authorize", "proactive", "transient", "terminal", "single-flight"]

for (const mode of cases) {
  test(`isolated Claude auth: ${mode}`, async () => {
    assert.ok(process.env.CLAUDE_AUTH_PLUGIN, "Set CLAUDE_AUTH_PLUGIN to the patched entrypoint")
    const root = process.env.OPENCODE_AUTH_TEST_ROOT || "/tmp/opencode"
    const home = await mkdtemp(path.join(root, "claude-auth-test-"))
    try {
      for (const dir of [".claude", "bin", "tmp"]) await mkdir(path.join(home, dir))
      // No inherited environment: debug paths, provider keys, Node preload hooks,
      // config overrides and refresh-lock paths must not escape this fixture.
      const env = {
        HOME: home, TMPDIR: path.join(home, "tmp"),
        CLAUDE_CONFIG_DIR: path.join(home, ".claude"),
        XDG_CONFIG_HOME: path.join(home, "config"), XDG_DATA_HOME: path.join(home, "data"),
        XDG_STATE_HOME: path.join(home, "state"), PATH: path.join(home, "bin"),
        CLAUDE_AUTH_PLUGIN: process.env.CLAUDE_AUTH_PLUGIN,
        OPENCODE_AUTH_TEST_ROOT: root,
        OPENCODE_CLAUDE_AUTH_REFRESH_WAIT_MS: "0", OPENCODE_CLAUDE_AUTH_MAX_RETRY_MS: "1",
      }
      await writeFile(path.join(home, "bin", "claude"), `#!${process.execPath}
        const fs = require('node:fs'), path = require('node:path')
        fs.appendFileSync(path.join(process.env.HOME, 'cli-calls'), 'call\\n')
        if (${JSON.stringify(mode)} === 'terminal') process.exit(1)
        setTimeout(() => {
          const file = path.join(process.env.CLAUDE_CONFIG_DIR, '.credentials.json')
          const data = JSON.parse(fs.readFileSync(file, 'utf8'))
          Object.assign(data.claudeAiOauth, {accessToken: 'fixture-cli', refreshToken: 'fixture-cli-refresh', expiresAt: Date.now() + 7200000})
          fs.writeFileSync(file, JSON.stringify(data))
        }, 150)
      `, { mode: 0o700 })
      const result = await run(process.execPath, [fixture, mode], { timeout: 15_000, env })
      assert.ok(result.stdout.includes(`"case":"${mode}"`), result.stdout)
    } finally {
      await rm(home, { recursive: true, force: true })
    }
  })
}
