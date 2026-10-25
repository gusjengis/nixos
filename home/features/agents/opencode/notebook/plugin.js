import { execFile } from "node:child_process"
import { readFile } from "node:fs/promises"
import os from "node:os"
import path from "node:path"
import { pathToFileURL } from "node:url"
import { createHooks } from "./runtime.mjs"

export const ContextNotebookPlugin = async ({ client }) => {
  // Local plugins are out-of-store symlinks. Resolve the SDK from OpenCode's
  // own config dependencies rather than requiring node_modules in this repo.
  const config = process.env.XDG_CONFIG_HOME || path.join(os.homedir(), ".config")
  const sdk = path.join(config, "opencode", "node_modules", "@opencode-ai", "plugin", "dist", "tool.js")
  const { tool } = await import(pathToFileURL(sdk).href)
  const source = await readFile(new URL("./SKILL.md", import.meta.url), "utf8")
  const skill = source.replace(/^---\n[\s\S]*?\n---\n/, "").trim()
  const run = (owner, action, payload) => new Promise((resolve, reject) => {
    const child = execFile("context-notes", ["--context", owner, action],
      { timeout: 15000, maxBuffer: 256 * 1024 }, (error, stdout, stderr) => {
        if (error) return reject(new Error(stderr.trim() || error.message))
        try { resolve(JSON.parse(stdout)) } catch (parseError) { reject(parseError) }
      })
    child.stdin.on("error", () => {})
    child.stdin.end(JSON.stringify(payload))
  })
  return createHooks({ client, tool, run, skill })
}
