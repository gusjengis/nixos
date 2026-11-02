/** @jsxImportSource @opentui/solid */
import { execFile } from "node:child_process"
import { readFileSync } from "node:fs"
import { join } from "node:path"
import { StaleController, needsBlock, revisionToken, selectedMember, verified } from "./context-stale-controller.mjs"
import { DraftStore, hasDraft } from "./context-stale-drafts.mjs"
import { readState, readVerdict, statePath, observeState } from "../context-state.mjs"

export default {
  id: "context-stale",
  tui: async (api) => {
    if (!process.env.CONTEXT_ID || process.env.OPENCODE_CONTEXT_HELPER) return
    const host = globalThis[Symbol.for("opencode.desktop.stale.v1")]
    if (host?.version !== 1) throw new Error("Blocking stale-session native support missing; install context-stale.patch.")
    const path = statePath(process.env)
    const store = new DraftStore(join(process.env.XDG_STATE_HOME ?? join(process.env.HOME, ".local/state"),
      "opencode-context", "stale-recovery"))
    let disposed = false
    let refreshing = false
    let armedAt = 0
    let wasBlocked = false
    const helper = (command, identity, revision) => new Promise((resolve, reject) => {
      const args = [command, "--owner", identity.owner, "--chat", identity.chat]
      if (command === "ensure") {
        args.push("--member", identity.member)
        if (revision != null) args.push("--expected-revision", revision)
      } else args.push("--session", identity.nativeID)
      execFile("opencode-context-chats", args, { timeout: 120000, maxBuffer: 4 * 1024 * 1024,
        signal: api.lifecycle.signal }, (error, stdout, stderr) => {
        if (error) return reject(new Error(stderr.trim() || error.message))
        try { resolve(JSON.parse(stdout)) } catch { reject(new Error("Invalid selected-conversation response")) }
      })
    })
    const recordOf = (value) => value?.record ?? value?.conversation ?? value
    const identity = () => {
      const route = api.route.current
      if (route.name !== "session") return
      const nativeID = route.params?.sessionID
      const info = api.state.session.get(nativeID)
      const marker = info?.metadata?.desktop_context
      if (!marker) return
      let root = info
      const seen = new Set()
      while (root?.parentID && !seen.has(root.id)) {
        seen.add(root.id)
        root = api.state.session.get(root.parentID)
      }
      return { owner: marker.id, chat: marker.chat, member: marker.session, nativeID,
        rootID: root && !root.parentID ? root.id : undefined }
    }
    const resolveIdentity = async () => {
      const cached = identity()
      if (cached?.rootID) return cached
      const route = api.route.current
      if (route.name !== "session") return
      const nativeID = route.params?.sessionID
      let info = (await api.client.session.get({ sessionID: nativeID }, { throwOnError: true })).data
      const marker = info?.metadata?.desktop_context
      if (!marker) throw new Error("Cannot verify conversation ownership")
      const seen = new Set()
      while (info.parentID) {
        if (seen.has(info.id)) throw new Error("Invalid conversation ancestry")
        seen.add(info.id)
        info = (await api.client.session.get({ sessionID: info.parentID }, { throwOnError: true })).data
      }
      if (api.route.current.name !== "session" || api.route.current.params?.sessionID !== nativeID) return
      return { owner: marker.id, chat: marker.chat, member: marker.session, nativeID, rootID: info.id }
    }
    const markerOf = (id) => ({ id: id.owner, chat: id.chat, session: id.member })
    const localVerdict = (id, nativeID = id.nativeID) => {
      const verdict = readVerdict(path, markerOf(id), nativeID, { rootID: id.rootID })
      const scope = JSON.parse(readFileSync(process.env.OPENCODE_CONTEXT_SCOPE_FILE, "utf8"))
      if (scope.context_id !== process.env.CONTEXT_ID || !scope.ids?.includes(id.owner)) {
        return { ...verdict, allowed: false, code: "unverified" }
      }
      if (scope.hidden?.includes(nativeID) || (nativeID === id.nativeID && scope.hidden?.includes(id.rootID))) {
        return { ...verdict, allowed: false, code: "outdated" }
      }
      return verdict
    }
    const snapshotRecord = async (id) => {
      const snapshot = await readState(path)
      return snapshot?.conversations?.[`${id.owner}/${id.chat}`]
    }
    const families = async (id) => {
      const get = async (sessionID) => {
        const response = await api.client.session.get({ sessionID }, { throwOnError: true })
        if (!response.data) throw new Error("Cannot inspect preserved conversation family")
        return response.data
      }
      let root = await get(id.nativeID)
      const ancestors = new Set()
      while (root.parentID) {
        if (ancestors.has(root.id)) throw new Error("Invalid conversation ancestry")
        ancestors.add(root.id)
        root = await get(root.parentID)
      }
      const selected = (await snapshotRecord(id))?.selected_root
      const found = new Map()
      const visit = async (info) => {
        if (found.has(info.id)) return
        found.set(info.id, info)
        const result = await api.client.session.children({ sessionID: info.id }, { throwOnError: true })
        for (const child of result.data ?? []) await visit(child)
      }
      await visit(root)
      if (selected && !found.has(selected)) await visit(await get(selected))
      return [...found.values()]
    }
    const activity = async (id) => {
      const family = await families(id)
      const response = await api.client.session.status({}, { throwOnError: true })
      if (!response.data) throw new Error("Cannot verify running work")
      return family.filter((info) => (response.data[info.id] && response.data[info.id].type !== "idle")
        || api.state.session.permission(info.id).length || api.state.session.question(info.id).length).map((info) => info.id)
    }
    const preserve = async (id) => {
      const histories = []
      for (const info of await families(id)) {
        const result = await api.client.session.messages({ sessionID: info.id }, { throwOnError: true })
        histories.push({ info, messages: result.data })
      }
      // Original native data/attachments remain in their database. This durable
      // additional export makes superseded messages discoverable outside picker.
      return store.preserve(id, histories)
    }
    const describe = (state) => {
      const record = state.record ?? controller.record
      const phase = state.phase
      const color = api.theme.current
      return <box flexDirection="column" gap={1}>
        <text fg={color.warning}><b>Newer conversation / recovery decision required</b></text>
        <text fg={color.text}>Updated on {record?.source_device ?? "unknown device"}. Current copy is blocked.</text>
        <text fg={color.textMuted}>State: {phase} · {record?.availability ?? "checking"} · revision {record?.known_revision ?? "unknown"}</text>
        {state.error && <text fg={color.error}>{state.error}</text>}
        {state.active?.length > 0 && <text fg={color.warning}>Running/pending family work: {state.active.join(", ")}</text>}
        <text fg={color.text}>{phase === "confirm-stop"
          ? "Enter: Stop running work and preserve history. W: Wait instead."
          : phase === "draft-conflict" ? "D: Use originating draft. L: Keep latest draft. Both copies are saved."
          : phase === "active" || phase === "waiting" ? "W: Wait for completion. S: Review stop-and-preserve decision."
          : "Enter: Open latest verified conversation"}</text>
        <text fg={color.textMuted}>P: Preserve/export both histories · R: Review missing-child root recovery · X: Save draft and exit</text>
        <text fg={color.textMuted}>Escape and backdrop cannot dismiss this screen. No stale continuation.</text>
        {state.recovery?.path && <text fg={color.textMuted}>Draft recovery: {state.recovery.path}</text>}
        {state.historyRecovery?.path && <text fg={color.textMuted}>History recovery: {state.historyRecovery.path}</text>}
      </box>
    }
    const handleKey = (event) => {
      if (Date.now() < armedAt || event.ctrl || event.meta || event.repeated) return
      const name = event.name?.toLowerCase()
      if (name === "return" || name === "enter") {
        void controller.act(controller.state.phase === "confirm-stop" ? "confirm-stop" : "open")
      } else if (name === "w") void controller.act("wait")
      else if (name === "s") void controller.act("stop")
      else if (name === "p") void controller.act("preserve")
      else if (name === "r") controller.chooseRoot()
      else if (name === "d") void controller.chooseDraft("origin")
      else if (name === "l") void controller.chooseDraft("latest")
      else if (name === "x") void Promise.resolve(controller.saved).then(() => api.keymap.dispatchCommand("app.exit"))
        .catch((error) => controller.publish({ phase: "error", error: error.message }))
    }
    const controller = new StaleController({
      capture: () => host.capture(),
      recover: async (id) => (await store.latest(id))?.draft,
      save: (id, draft, reason) => store.save(id, draft, reason),
      check: async (id) => recordOf(await helper("check", id)),
      ensure: (id, revision) => helper("ensure", id, revision),
      activity,
      stop: async (ids) => {
        for (const sessionID of ids) await api.client.session.abort({ sessionID }, { throwOnError: true })
      },
      preserve,
      destinationDraft: async (nativeID) => {
        const current = host.destination(nativeID)
        return hasDraft(current) ? current : (await store.latest({ ...controller.identity, nativeID }))?.draft
      },
      route: (sessionID, draft, record) => host.handoff(sessionID, draft, () => {
        // OC5 adapter is synchronous local-file IO. Reject rather than routing
        // if a future adapter changes this API to an async reader.
        const verdict = localVerdict(controller.identity, sessionID)
        return !verdict?.then && verdict.allowed && verified(verdict.record)
          && revisionToken(verdict.record) === revisionToken(record)
          && selectedMember(verdict.record, controller.identity) === sessionID
      }, () => api.route.navigate("session", { sessionID })),
      render: (state) => {
        if (state.blocked) {
          if (!wasBlocked) armedAt = Date.now() + 250
          host.block(() => describe(state), handleKey)
        } else host.clear()
        wasBlocked = state.blocked
      },
    })
    const refresh = async () => {
      if (disposed || refreshing) return
      refreshing = true
      try {
        const id = await resolveIdentity()
        if (!id) return
        const verdict = localVerdict(id)
        // A changed shared archive head can be our checkpoint or another chat.
        // Wait for discovery to classify it before latching a stale overlay.
        if (verdict.code === "waiting_data" && !needsBlock(verdict.record, id) && !controller.state.blocked) return
        await controller.observe(id, verdict.record, undefined, !verdict.allowed)
      } catch (error) {
        const id = identity() ?? controller.identity
        if (id) await controller.observe(id, controller.record, undefined, true)
        controller.publish({ phase: "error", error: `Cannot verify freshness: ${error.message}` })
      } finally { refreshing = false }
    }
    const unconfigure = host.configure({
      guard: async () => {
        let id
        try {
          id = await resolveIdentity()
          if (!id) return api.route.current.name !== "session"
          const verdict = localVerdict(id)
          if (verdict.allowed && !needsBlock(verdict.record, id)) return true
          if (verdict.code === "waiting_data" && !needsBlock(verdict.record, id)) return false
          await controller.observe(id, verdict.record, undefined, true)
        } catch (error) {
          id ??= identity() ?? controller.identity
          if (id) await controller.observe(id, controller.record, undefined, true)
          controller.publish({ phase: "error", error: error.message })
        }
        return false
      },
      rejected: async (nativeID, draft, _error) => {
        const id = await resolveIdentity()
        if (!id || id.nativeID !== nativeID) {
          await store.save({ nativeID }, draft, "rejected-send")
          return
        }
        const verdict = localVerdict(id, nativeID)
        if (verdict.code === "waiting_data" && !needsBlock(verdict.record, id)) {
          await store.save(id, draft, "rejected-send")
          return
        }
        if (!verdict.allowed || needsBlock(verdict.record, id)) {
          // Preserve both the rejected dispatch and any newer visible typing.
          await store.save(id, draft, "rejected-send")
          await controller.observe(id, verdict.record, undefined, true)
        }
      },
    })
    const unobserve = observeState(path, () => { void refresh() })
    const timer = setInterval(() => { void refresh() }, 500)
    timer.unref?.()
    api.lifecycle.onDispose(() => {
      disposed = true
      clearInterval(timer)
      unobserve?.()
      unconfigure()
    })
    void refresh()
  },
}
