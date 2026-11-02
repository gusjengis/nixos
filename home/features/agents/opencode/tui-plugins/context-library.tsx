/** @jsxImportSource @opentui/solid */
import { execFile } from "node:child_process"
import { createSignal } from "solid-js"
import { createHistoryClient, rowStatus } from "../history-client.mjs"
import { historyStatus } from "../history-controller.mjs"

export default {
  id: "context-library",
  tui: async (api) => {
    const owner = process.env.CONTEXT_ID
    if (!owner) return
    const history = createHistoryClient()
    const [state, setState] = createSignal<any>({ loaded: false, summaries: [] })
    const [snapshot, setSnapshot] = createSignal<any>({ conversations: {} })
    let disposed = false
    const discover = async () => {
      try { const value = await history.list(); if (!disposed) setState(value) }
      catch (error) { if (!disposed) setState((old) => ({ ...old, error: error.message })) }
    }
    const stop = history.observe((value, meta) => {
      if (disposed) return
      if (!value) { setState((old) => ({ ...old, error: meta?.error?.message || "History state unavailable" })); return }
      setSnapshot(value)
    })
    void discover()
    const Status = () => {
      const message = () => {
        const route = api.route.current
        const session = route.name === "session" ? api.state.session.get(route.params.sessionID) : undefined
        const marker = session?.metadata?.desktop_context
        const record = marker && snapshot().conversations?.[`${marker.id}/${marker.chat}`]
        if (state().error || state().operation) return historyStatus(state(), 0)
        if (record) return rowStatus(record)
        const active: any = Object.values(snapshot().conversations ?? {}).find((record: any) =>
          record.operation?.phase && record.operation.phase !== "idle")
        return active ? rowStatus(active) : historyStatus(state(), state().summaries?.length ?? 0)
      }
      return <text fg={api.theme.current.textMuted}>History: {message()}</text>
    }
    const Footer = (props: { sessionID: string }) => {
      const path = () => {
        const session = api.state.session.get(props.sessionID)
        const directory = session?.directory || api.state.path.directory || process.cwd()
        const home = process.env.HOME
        const abbreviated = home && (directory === home || directory.startsWith(`${home}/`))
          ? `~${directory.slice(home.length)}` : directory
        const branch = session?.directory === api.state.path.directory ? api.state.vcs?.branch : undefined
        const parts = (branch ? `${abbreviated}:${branch}` : abbreviated).split("/")
        return { parent: parts.slice(0, -1).join("/"), name: parts.at(-1) ?? "" }
      }
      return <box>
        <Status />
        <text>
          <span style={{ fg: api.theme.current.textMuted }}>{path().parent}/</span>
          <span style={{ fg: api.theme.current.text }}>{path().name}</span>
        </text>
        <text marginTop={1} fg={api.theme.current.textMuted}>
          <span style={{ fg: api.theme.current.success }}>•</span> <b>Open</b>
          <span style={{ fg: api.theme.current.text }}><b>Code</b></span>{" "}
          <span>{api.app.version}</span>
        </text>
      </box>
    }
    api.slots.register({ order: 900, slots: {
      sidebar_footer: (_ctx, props) => <Footer sessionID={props.session_id} />,
    } })
    api.lifecycle.onDispose(() => { disposed = true; stop(); history.cancel() })
    const helper = (command) => new Promise((resolve, reject) => {
      execFile("opencode-context-chats", [command], { timeout: 120000 }, (error, stdout, stderr) => {
        if (error) reject(new Error(stderr.trim() || error.message))
        else resolve(stdout)
      })
    })
    const sync = async () => {
      setState((old) => ({ ...old, operation: { phase: "updating" }, error: undefined }))
      try { await helper("sync"); await discover() }
      catch (error) { setState((old) => ({ ...old, operation: undefined, error: error.message })); throw error }
    }
    const report = (error) => api.ui.toast({ title: "Context chat library", message: error.message, variant: "error" })
    const adopt = async (sessionID) => {
      try {
        const route = api.route.current
        sessionID ??= route.name === "session" ? route.params.sessionID : undefined
        if (!sessionID) throw new Error("Open a conversation first.")
        let session = (await api.client.session.get({ sessionID }, { throwOnError: true })).data
        while (session.parentID) session = (await api.client.session.get({ sessionID: session.parentID }, { throwOnError: true })).data
        const origin = session.id
        const family = []
        const visit = async (info) => {
          const marker = info.metadata?.desktop_context
          if (marker && (marker.id !== owner || marker.chat !== origin)) throw new Error("Conversation already has an owner; ownership stays with that context.")
          family.push(info)
          for (const child of (await api.client.session.children({ sessionID: info.id }, { throwOnError: true })).data ?? []) await visit(child)
        }
        await visit(session)
        for (const info of family) {
          await api.client.session.update({ sessionID: info.id, metadata: {
            ...info.metadata, desktop_context: { id: owner, chat: origin, session: info.id },
          } }, { throwOnError: true })
        }
        await sync()
        api.route.navigate("session", { sessionID })
        api.ui.toast({ message: "Conversation assigned and saved to this context's portable library.", variant: "success" })
      } catch (error) { report(error) }
    }
    const confirm = (sessionID) => api.ui.dialog.replace(() => <api.ui.DialogConfirm title="Assign conversation?"
      message="Assign this unowned conversation and its subagents to the current context's portable chat library."
      onConfirm={() => { api.ui.dialog.clear(); void adopt(sessionID) }} />)
    const remove = api.keymap.registerLayer({
      commands: [
        { name: "context.chat.adopt", title: "Assign unowned conversation to this context", category: "Session",
          run: () => confirm(api.route.current.name === "session" ? api.route.current.params.sessionID : undefined) },
        { name: "context.chat.import", title: "Browse unowned conversations to assign to this context", category: "Session",
          run: async () => {
            try {
              const sessions = JSON.parse(await helper("unowned"))
              api.ui.dialog.replace(() => <api.ui.DialogSelect title="Unowned conversations in this working directory"
                options={sessions.map((session) => ({ title: session.title, description: session.directory, value: session.id }))}
                onSelect={(option) => confirm(option.value)} />)
            } catch (error) { report(error) }
          } },
        { name: "context.chat.sync", title: "Sync portable context chat libraries", category: "Session",
          run: () => { void sync().catch(report) } },
      ],
    })
    api.lifecycle.onDispose(remove)
  },
}
