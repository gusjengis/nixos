// NOTIFY_PLUGIN points to peripheral-plugins.nix's patched session-notify.js.
import assert from "node:assert/strict"
import { execFile } from "node:child_process"
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { promisify } from "node:util"
import { test } from "node:test"

const run = promisify(execFile)
for (const mode of ["status", "theme", "persistence", "notify-hang", "notify-ready"]) {
  test(`bounded peripheral: ${mode}`, async () => {
    assert.ok(process.env.NOTIFY_PLUGIN, "Set NOTIFY_PLUGIN to patched notification entrypoint")
    const home = await mkdtemp("/tmp/opencode/peripheral-test-")
    try {
      await mkdir(path.join(home, "bin"))
      await writeFile(path.join(home, "bin/tmux"), `#!${process.execPath}
        const fs = require('node:fs'), path = require('node:path')
        const log = path.join(process.env.HOME, 'tmux-calls')
        const first = !fs.existsSync(log)
        fs.appendFileSync(log, JSON.stringify({pid:process.pid,args:process.argv.slice(2)}) + '\\n')
        if (process.env.CASE !== 'notify-ready' && first) {
          process.on('SIGTERM', () => {})
          setInterval(() => {}, 1000)
        } else if (process.argv.includes('display-message')) {
          process.stdout.write(process.env.CASE === 'persistence' ? String(process.ppid) : '$fixture\\tcontext-name\\tclient-name\\n')
        }
      `, { mode: 0o700 })
      await writeFile(path.join(home, "bin/opencode-session-notify"), `#!${process.execPath}
        require('node:fs').writeFileSync(require('node:path').join(process.env.HOME, 'notification'), JSON.stringify(process.argv.slice(2)))
      `, { mode: 0o700 })
      const result = await run(process.execPath, [fileURLToPath(new URL("./peripheral-fixture.mjs", import.meta.url)), mode], {
        timeout: 10_000, env: { HOME: home, TMPDIR: home, PATH: path.join(home, "bin"),
          TMUX_PANE: "%fixture", TMUX: "/fixture-socket,1,2", XDG_RUNTIME_DIR: home,
          OPENCODE_DB: path.join(home, "custom.db"), CASE: mode, NOTIFY_PLUGIN: process.env.NOTIFY_PLUGIN },
      })
      assert.ok(result.stdout.includes(`"case":"${mode}"`))
    } finally { await rm(home, { recursive: true, force: true }) }
  })
}
