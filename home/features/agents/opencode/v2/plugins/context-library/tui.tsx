/** @jsxImportSource @opentui/solid */
import { execFile } from "node:child_process"
import { createSignal } from "solid-js"
import { createHistoryClient, rowStatus } from "../../../history-client.mjs"
import { historyStatus } from "../../../history-controller.mjs"
import { ContextLibraryRPC } from "./rpc.mjs"

export default {
  id: "desktop.context-library",
  async setup(ctx) {
    const owner = process.env.CONTEXT_ID
    if (!owner) return
    const history = createHistoryClient()
    const [state, setState] = createSignal<any>({ loaded: false, summaries: [] })
    const [snapshot, setSnapshot] = createSignal<any>({ conversations: {} })
    let disposed = false
    const signal = new AbortController()
    const discover = async () => {
      try { const value = await history.list(); if (!disposed) setState(value) }
      catch (error) { if (!disposed) setState((old) => ({ ...old, error: error.message })) }
    }
    const stop = history.observe((value, meta) => {
      if (disposed) return
      if (!value) { setState((old) => ({ ...old, error: meta?.error?.message || "History state unavailable" })); return }
      setSnapshot(value)
    })
    const stopNotices = ctx.client.rpc(ContextLibraryRPC).events.on("notice", (event) => ctx.ui.toast.show(event.data))
    void discover()
    const Footer = (props: { sessionID: string }) => {
      const message = () => {
        const session = ctx.data.session.get(props.sessionID)
        const marker = session?.metadata?.desktop_context
        const record = marker && snapshot().conversations?.[`${marker.id}/${marker.chat}`]
        if (state().error || state().operation) return historyStatus(state(), 0)
        if (record) return rowStatus(record)
        const active: any = Object.values(snapshot().conversations ?? {}).find((record: any) =>
          record.operation?.phase && record.operation.phase !== "idle")
        return active ? rowStatus(active) : historyStatus(state(), state().summaries?.length ?? 0)
      }
      const path = () => {
        const location = ctx.data.session.get(props.sessionID)?.location ?? ctx.location ?? ctx.data.location.default()
        const directory = location.directory
        const home = process.env.HOME
        const abbreviated = home && (directory === home || directory.startsWith(`${home}/`)) ? `~${directory.slice(home.length)}` : directory
        const branch = ctx.data.location.vcs.info(location)?.branch.current
        const parts = (branch ? `${abbreviated}:${branch}` : abbreviated).split("/")
        return { parent: parts.slice(0, -1).join("/"), name: parts.at(-1) ?? "" }
      }
      return <box flexDirection="column">
        <text fg={ctx.theme.text.muted}>History: {message()}</text>
        <text><span style={{ fg: ctx.theme.text.muted }}>{path().parent}/</span><span style={{ fg: ctx.theme.text.base }}>{path().name}</span></text>
        <text marginTop={1} fg={ctx.theme.text.muted}><span style={{ fg: ctx.theme.text.feedback.success.base }}>•</span> <b>OpenCode</b> {ctx.app.version}</text>
      </box>
    }
    const removeFooter = ctx.ui.slot({ replace: "sidebar.footer", render: (props) => <Footer sessionID={props.sessionID} /> })
    const helper = (command, ...args: string[]) => new Promise<string>((resolve, reject) => {
      execFile("opencode-context-chats", [command, ...args], { timeout: 120000, signal: signal.signal }, (error, stdout, stderr) => {
        if (error) reject(new Error(stderr.trim() || error.message))
        else resolve(stdout)
      })
    })
    const sync = async () => {
      setState((old) => ({ ...old, operation: { phase: "updating" }, error: undefined }))
      try { await helper("sync"); await discover() }
      catch (error) { setState((old) => ({ ...old, operation: undefined, error: error.message })); throw error }
    }
    const report = (error) => ctx.ui.toast.show({ title: "Context chat library", message: error.message, variant: "error" })
    const currentID = () => {
      const route = ctx.ui.router.current()
      if (route.type !== "session") throw new Error("Open a conversation first.")
      return route.sessionID
    }
    const rootOf = async (sessionID) => {
      let session = await ctx.client.session.get({ sessionID })
      const seen = new Set()
      while (session.parentID) {
        if (seen.has(session.id)) throw new Error("Invalid conversation ancestry")
        seen.add(session.id)
        session = await ctx.client.session.get({ sessionID: session.parentID })
      }
      return session
    }
    const children = async (sessionID) => {
      const rows = []
      let cursor
      do {
        const page = await ctx.client.session.list(cursor ? { cursor, limit: 100 } : { parentID: sessionID, limit: 100 })
        rows.push(...page.data)
        cursor = page.cursor?.next
      } while (cursor)
      return rows
    }
    const familyOf = async (root) => {
      const rows = [], seen = new Set()
      const visit = async (session) => {
        if (seen.has(session.id)) throw new Error("Invalid conversation ancestry")
        seen.add(session.id); rows.push(session)
        for (const child of await children(session.id)) await visit(child)
      }
      await visit(root)
      return rows
    }
    const adopt = async (sessionID = currentID()) => {
      if (!(await ctx.ui.dialog.confirm({ title: "Assign conversation?", message: "Assign this unowned conversation and its subagents to the current context's portable chat library." }))) return
      const root = await rootOf(sessionID)
      const family = await familyOf(root)
      for (const info of family) {
        const marker = info.metadata?.desktop_context
        if (marker && (marker.id !== owner || marker.chat !== root.id)) throw new Error("Conversation already has an owner; ownership stays with that context.")
      }
      for (const info of family) await ctx.client.session.update({ sessionID: info.id, metadata: {
        ...info.metadata, desktop_context: { id: owner, chat: root.id, session: info.id },
      } })
      await sync()
      ctx.ui.router.navigate({ type: "session", sessionID })
      ctx.ui.toast.show({ message: "Conversation assigned and saved to this context's portable library.", variant: "success" })
    }
    const move = async () => {
      const sessionID = currentID()
      const root = await rootOf(sessionID)
      const marker = root.metadata?.desktop_context
      if (!marker) throw new Error("Assign this conversation to a context before moving it.")
      const options = JSON.parse(await helper("destinations", "--session", sessionID))
        .filter((context) => context.id !== marker.id || context.retry)
        .map((context) => ({ title: context.title, description: context.retry ? `${context.directory} — finish interrupted move` : context.directory, value: context.id }))
      const target = await ctx.ui.dialog.select({ title: "Move session to context", options })
      if (!target) return
      const selected = options.find((option) => option.value === target)
      if (!(await ctx.ui.dialog.confirm({ title: `Move to ${selected.title}?`, message: "Move this conversation and its subagents into the destination context's portable chat library. Working directory stays the same. Open the destination context to continue there." }))) return
      const statuses = await ctx.client.session.active()
      for (const info of await familyOf(root)) {
        if (statuses[info.id] || ctx.data.session.permission.list(info.id)?.length || ctx.data.session.form.list(info.id)?.length)
          throw new Error("Wait for this conversation and its subagents to finish before moving.")
      }
      ctx.ui.toast.show({ message: "Moving conversation…", variant: "info" })
      await helper("move", "--session", sessionID, "--target", target)
      ctx.ui.router.navigate({ type: "home" })
      await discover()
      ctx.ui.toast.show({ message: `Conversation moved to ${selected.title}. Open that context to continue.`, variant: "success" })
    }
    const safely = (action) => () => { void Promise.resolve().then(action).catch(report) }
    ctx.keymap.layer(() => ({ commands: [
      { id: "context.chat.move", title: "Move session to context", group: "Session", palette: true, run: safely(move) },
      { id: "context.chat.adopt", title: "Assign unowned conversation to this context", group: "Session", palette: true, run: safely(() => adopt()) },
      { id: "context.chat.import", title: "Browse unowned conversations to assign to this context", group: "Session", palette: true, run: safely(async () => {
        const sessions = JSON.parse(await helper("unowned"))
        const selected = await ctx.ui.dialog.select({ title: "Unowned conversations in this working directory",
          options: sessions.map((session) => ({ title: session.title, description: session.directory, value: session.id })) })
        if (selected) await adopt(selected)
      }) },
      { id: "context.chat.sync", title: "Sync portable context chat libraries", group: "Session", palette: true, run: safely(sync) },
    ] }))
    return () => { disposed = true; signal.abort(); stop(); stopNotices(); removeFooter(); history.cancel() }
  },
}
