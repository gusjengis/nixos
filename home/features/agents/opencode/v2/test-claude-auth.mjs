import assert from "node:assert/strict"
import { chmod, cp, mkdir, mkdtemp, rm, writeFile } from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import test from "node:test"
const execute = promisify(execFile)
const source = process.env.CLAUDE_AUTH_V2_SOURCE

for (const mode of ["startup", "refresh", "switch", "cli-fallback"]) {
  test(`V2 Claude auth: ${mode}`, { skip: !source }, async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "claude-auth-v2-test-"))
    try {
      const plugin = path.join(root, "plugin")
      await cp(source, plugin, { recursive: true })
      await chmod(plugin, 0o700)
      const sdk = path.join(plugin, "node_modules/@opencode/plugin")
      await mkdir(sdk, { recursive: true })
      await writeFile(path.join(sdk, "package.json"), JSON.stringify({ type: "module", exports: "./index.js" }))
      await writeFile(path.join(sdk, "index.js"), `
        const identity = { make: value => value };
        export const Plugin = { define: value => value };
        export const Provider = { ID: identity };
        export const Integration = { ID: identity, MethodID: identity };
        export const Credential = { OAuth: identity };
      `)
      const bin = path.join(root, "bin")
      await mkdir(bin)
      await writeFile(path.join(bin, "claude"), `#!${process.execPath}
        import fs from 'node:fs';
        setTimeout(() => fs.writeFileSync(process.env.HOME + '/.claude/.credentials.json', JSON.stringify({ claudeAiOauth: {
          accessToken: 'fixture-cli', refreshToken: 'fixture-cli-refresh', expiresAt: Date.now() + 7200000
        } })), 200);
      `, { mode: 0o700 })
      const fixture = new URL("./claude-auth-fixture.mjs", import.meta.url)
      const result = await execute(process.execPath, [fixture.pathname, mode, plugin], {
        timeout: 15000,
        env: { ...process.env, HOME: root, XDG_DATA_HOME: path.join(root, "data"),
          XDG_CONFIG_HOME: path.join(root, "config"), CLAUDE_CONFIG_DIR: path.join(root, ".claude"),
          PATH: bin + path.delimiter + process.env.PATH },
      })
      assert.match(result.stdout, /PASS/)
    } finally { await rm(root, { recursive: true, force: true }) }
  })
}
