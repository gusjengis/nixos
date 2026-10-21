/** @jsxImportSource @opentui/solid */
import { execFile } from "node:child_process"

export default {
  id: "context-library",
  tui: async (api) => {
    const owner = process.env.CONTEXT_ID
    if (!owner) return
    const helper = (command) => new Promise((resolve, reject) => {
      execFile("opencode-context-chats", [command], { timeout: 120000 }, (error, stdout, stderr) => {
        if (error) reject(new Error(stderr.trim() || error.message))
        else resolve(stdout)
      })
    })
    const sync = () => helper("sync")
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
          run: () => { void sync().then(() => api.ui.toast({ message: "Context chat libraries synchronized.", variant: "success" })).catch(report) } },
      ],
    })
    api.lifecycle.onDispose(remove)
  },
}
