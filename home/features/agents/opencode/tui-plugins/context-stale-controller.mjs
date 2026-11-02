import { hasDraft, sameDraft } from "./context-stale-drafts.mjs"

export const clone = (value) => value == null ? value : JSON.parse(JSON.stringify(value))
export const revisionToken = (record) => JSON.stringify([
  record?.generation, record?.known_revision, record?.selected_root, record?.members,
  record?.freshness, record?.availability, record?.operation?.phase,
])

export function selectedMember(record, identity) {
  return record?.members?.[identity.member] ?? (identity.member === identity.chat ? record?.selected_root : undefined)
}

export function needsBlock(record, identity) {
  if (!record) return false
  if (["outdated", "conflict", "deleted"].includes(record.freshness)) return true
  const selected = selectedMember(record, identity)
  return Boolean(selected && selected !== identity.nativeID)
}

export function verified(record) {
  return record?.freshness === "current_as_known" && record.availability === "local"
    && record.operation?.phase === "idle" && Boolean(record.known_revision)
    && record.base_revision === record.known_revision
}

// State machine deliberately independent of terminal widgets and backend workers.
// Once blocked, only a checked, deliberate handoff can unlock the conversation.
export class StaleController {
  constructor(io) {
    this.io = io
    this.state = { phase: "idle", blocked: false }
    this.busy = false
    this.epoch = 0
  }

  publish(change) {
    this.state = { ...this.state, ...change }
    this.io.render(this.state)
  }

  async observe(identity, record, rejectedDraft, force = false) {
    if (!identity || (!this.state.blocked && !force && !needsBlock(record, identity))) return
    const different = this.identity && (identity.owner !== this.identity.owner || identity.chat !== this.identity.chat
      || identity.nativeID !== this.identity.nativeID)
    if (different && this.state.blocked) return
    this.identity = clone(identity)
    const token = revisionToken(record)
    const changed = token !== this.token
    if (record?.known_revision !== this.record?.known_revision) this.epoch++
    this.token = token
    this.record = clone(record)
    if (!this.state.blocked) {
      this.draft = clone(rejectedDraft ?? this.io.capture())
      // Freeze synchronously, before disk IO or any import/check await.
      this.publish({ blocked: true, phase: "saving", error: undefined })
      this.saved = (async () => {
        if (!hasDraft(this.draft) && this.io.recover) {
          this.draft = clone(await this.io.recover(this.identity) ?? this.draft)
        }
        return this.io.save(this.identity, this.draft)
      })()
    } else if (rejectedDraft && !sameDraft(rejectedDraft, this.draft)) {
      // A late rejection may contain a different draft than the visible editor.
      await this.io.save(this.identity, rejectedDraft, "rejected-send")
    }
    try {
      this.recovery = await this.saved
      const active = await this.io.activity(this.identity)
      if (this.busy) return
      // Polling must not erase a deliberate stop/draft/root decision or error.
      if (!changed && !["saving", "active", "waiting"].includes(this.state.phase)) {
        this.publish({ active, record: clone(record), recovery: this.recovery })
        return
      }
      this.publish({ phase: active.length ? "active" : record?.freshness === "conflict" ? "conflict" : "ready",
        active, record: clone(record), recovery: this.recovery, error: undefined })
    } catch (error) { this.publish({ phase: "error", error: error.message }) }
  }

  async act(action) {
    if (!this.state.blocked || this.busy) return
    if (action === "stop") {
      this.publish({ phase: "confirm-stop" })
      return
    }
    if (action === "wait") {
      this.publish({ phase: "waiting", error: undefined })
      return
    }
    if (action !== "open" && action !== "preserve" && action !== "confirm-stop") return
    this.busy = true
    const epoch = this.epoch
    const token = this.token
    try {
      await this.saved
      const fresh = await this.io.check(this.identity)
      if (revisionToken(fresh) !== token || epoch !== this.epoch) {
        this.busy = false
        await this.observe(this.identity, fresh)
        this.publish({ error: "Conversation changed. Review update, then press Enter again." })
        return
      }
      let active = await this.io.activity(this.identity)
      if (active.length) {
        if (action !== "confirm-stop" || this.state.phase !== "confirm-stop") {
          this.publish({ phase: "active", active })
          return
        }
        this.publish({ phase: "stopping" })
        await this.io.stop(active)
        active = await this.io.activity(this.identity)
        if (active.length) throw new Error("Running work has not stopped; both histories retained.")
        await this.io.preserve(this.identity)
        this.publish({ phase: "ready", error: "Work stopped and preserved. Press Enter to open latest." })
        return
      }
      if (action === "preserve") {
        this.publish({ phase: "preserving" })
        const recovery = await this.io.preserve(this.identity)
        this.publish({ phase: fresh?.freshness === "conflict" ? "conflict" : fresh?.freshness === "deleted" ? "deleted" : "ready",
          historyRecovery: recovery, error: "Both histories preserved. Opening latest remains a separate deliberate decision." })
        return
      }
      if (fresh?.freshness === "conflict") {
        this.publish({ phase: "conflict", error: "Preserve both histories and resolve backend conflict before opening latest." })
        return
      }
      if (fresh?.freshness === "deleted") throw new Error("Portable conversation deleted. Preserve/export local history before recovery.")
      // Superseded native IDs can contain edits the selected ledger ignores.
      // Always leave a discoverable local recovery export before abandoning one.
      this.historyRecovery = await this.io.preserve(this.identity)
      this.publish({ phase: "importing", error: undefined })
      const result = await this.io.ensure(this.identity, fresh?.known_revision)
      const latest = await this.io.check(this.identity)
      // Import is allowed to change availability/mapping/generation, not the
      // revision the user deliberately acknowledged. Any newer revision re-arms.
      if (epoch !== this.epoch || latest?.known_revision !== fresh?.known_revision) {
        this.busy = false
        await this.observe(this.identity, latest)
        this.publish({ error: "Newer update arrived. Press Enter to acknowledge its revision." })
        return
      }
      this.record = clone(latest)
      this.token = revisionToken(latest)
      const target = selectedMember(latest, this.identity)
      if (!verified(latest) || !target || result?.session_id !== target) {
        throw new Error(!target ? "Selected child missing from latest copy. Explicit root recovery required."
          : "Latest conversation is not fully imported and verified.")
      }
      if ((await this.io.activity(this.identity)).length) {
        this.publish({ phase: "active", error: "Work started during handoff. Review running work." })
        return
      }
      const beforeRoute = await this.io.check(this.identity)
      if (revisionToken(beforeRoute) !== revisionToken(latest) || epoch !== this.epoch) {
        this.busy = false
        await this.observe(this.identity, beforeRoute)
        this.publish({ error: "Conversation changed before switching. Press Enter again." })
        return
      }
      const destination = await this.io.destinationDraft(target)
      if (hasDraft(destination) && !sameDraft(destination, this.draft)) {
        await this.io.save({ ...this.identity, nativeID: target }, destination, "destination-draft")
        this.publish({ phase: "draft-conflict", target,
          error: "Both drafts saved. Press D to use originating draft, or L to keep latest draft." })
        this.pendingDrafts = { target, latest: destination, token: revisionToken(beforeRoute), epoch }
        return
      }
      await this.finish(target, this.draft, revisionToken(beforeRoute), epoch)
    } catch (error) {
      this.publish({ phase: "error", error: error.message })
    } finally { this.busy = false }
  }

  async chooseDraft(choice) {
    if (this.busy || this.state.phase !== "draft-conflict" || !this.pendingDrafts) return
    const pending = this.pendingDrafts
    this.busy = true
    try {
      await this.finish(pending.target, choice === "latest" ? pending.latest : this.draft, pending.token, pending.epoch)
    } catch (error) { this.publish({ phase: "error", error: error.message }) }
    finally { this.busy = false }
  }

  chooseRoot() {
    if (this.busy || !this.state.blocked || !this.state.error?.includes("Selected child missing")) return
    this.identity.member = this.identity.chat
    this.publish({ phase: "root-confirm", error: "Open latest root instead of missing child? Press Enter to confirm." })
  }

  async finish(target, draft, token, epoch) {
    const record = await this.io.check(this.identity)
    if (epoch !== this.epoch || revisionToken(record) !== token || !verified(record)
      || selectedMember(record, this.identity) !== target) {
      this.busy = false
      await this.observe(this.identity, record)
      this.publish({ error: "Conversation changed before switching. Press Enter again." })
      return
    }
    if ((await this.io.activity(this.identity)).length) {
      this.publish({ phase: "active", error: "Running work prevents handoff." })
      return
    }
    // route() performs one final synchronous local-state check in the native
    // bridge; there is no await between its check and permitted navigation.
    await this.io.route(target, clone(draft), record)
    this.publish({ blocked: false, phase: "idle" })
  }
}
