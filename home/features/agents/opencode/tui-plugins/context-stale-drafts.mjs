import { mkdir, open, readFile, readdir, rename } from "node:fs/promises"
import { createHash, randomUUID } from "node:crypto"
import { join } from "node:path"

const clone = (value) => JSON.parse(JSON.stringify(value))
const digest = (value) => createHash("sha256").update(JSON.stringify(value)).digest("hex")

// Private, device-local recovery records. Never synced or silently overwritten.
export class DraftStore {
  constructor(root) { this.root = root }

  async atomic(path, value) {
    await mkdir(this.root, { recursive: true, mode: 0o700 })
    const temporary = `${path}.${randomUUID()}.tmp`
    const file = await open(temporary, "wx", 0o600)
    try {
      await file.writeFile(JSON.stringify(value))
      await file.sync()
    } finally { await file.close() }
    await rename(temporary, path)
    const directory = await open(this.root, "r")
    try { await directory.sync() } finally { await directory.close() }
  }

  async save(identity, draft, reason = "superseded") {
    const payload = { identity: clone(identity), draft: clone(draft), reason }
    const id = digest(payload)
    const record = { version: 1, id, created: Date.now(), ...payload }
    await this.atomic(join(this.root, `${id}.json`), record)
    return { ...record, path: join(this.root, `${id}.json`) }
  }

  async load(id) {
    if (!/^[a-f0-9]{64}$/.test(id)) throw new Error("Invalid recovery draft ID")
    return JSON.parse(await readFile(join(this.root, `${id}.json`), "utf8"))
  }

  async latest(identity) {
    let names
    try { names = await readdir(this.root) }
    catch (error) { if (error.code === "ENOENT") return; throw error }
    let latest
    for (const name of names) {
      if (!/^[a-f0-9]{64}\.json$/.test(name)) continue
      const record = await this.load(name.slice(0, -5))
      if (record.reason === "preserved-history" || record.identity.nativeID !== identity.nativeID
        || record.identity.owner !== identity.owner || record.identity.chat !== identity.chat) continue
      if (!latest || record.created > latest.created) latest = record
    }
    return latest
  }

  async preserve(identity, histories) {
    return this.save(identity, { histories }, "preserved-history")
  }
}

export function hasDraft(value) {
  return Boolean(value?.prompt?.input || value?.prompt?.parts?.length)
}

export function sameDraft(left, right) {
  return JSON.stringify(left) === JSON.stringify(right)
}
