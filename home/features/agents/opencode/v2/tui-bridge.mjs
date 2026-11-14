// Narrow bridge for the existing persistence and stale-recovery controllers.
// The V2 UI remains native; only the data/client names used by those controllers
// are translated here. No hooks, permissions, or arbitrary SDK calls are guessed.
export function tuiBridge(ctx) {
  const controller = new AbortController()
  const cleanups = []
  const info = (session) => session && { ...session, directory: session.location.directory }
  const route = () => {
    const current = ctx.ui.router.current()
    return { name: current.type, params: current.type === "session" ? { sessionID: current.sessionID } : {} }
  }
  const api = {
    app: ctx.app,
    lifecycle: { signal: controller.signal, onDispose: (cleanup) => { cleanups.push(cleanup) } },
    route: {
      get current() { return route() },
      navigate: (type, params) => ctx.ui.router.navigate({ type, ...params }),
    },
    theme: { get current() { return {
      text: ctx.theme.text.base, textMuted: ctx.theme.text.muted,
      warning: ctx.theme.text.feedback.warning.base, error: ctx.theme.text.feedback.error.base,
      success: ctx.theme.text.feedback.success.base, info: ctx.theme.text.feedback.info.base,
    } } },
    keymap: { dispatchCommand: (id) => ctx.keymap.dispatch(id) },
    state: {
      get path() { return { directory: (ctx.location ?? ctx.data.location.default()).directory } },
      session: {
        get: (id) => info(ctx.data.session.get(id)),
        permission: (id) => ctx.data.session.permission.list(id) ?? [],
        question: (id) => ctx.data.session.form.list(id) ?? [],
      },
    },
    client: { session: {
      get: async ({ sessionID }) => {
        const session = await ctx.client.session.get({ sessionID })
        return { data: info(session) }
      },
      children: async ({ sessionID }) => {
        const rows = []
        let cursor
        const seen = new Set()
        do {
          const response = await ctx.client.session.list(cursor ? { cursor, limit: 100 } : { parentID: sessionID, limit: 100 })
          rows.push(...response.data.map(info))
          cursor = response.cursor?.next
          if (cursor && seen.has(cursor)) throw new Error("Repeated session-family cursor")
          if (cursor) seen.add(cursor)
        } while (cursor)
        return { data: rows }
      },
      status: async () => ({ data: await ctx.client.session.active() }),
      abort: ({ sessionID }) => ctx.client.session.interrupt({ sessionID }),
      messages: async ({ sessionID }) => {
        const exported = await ctx.client.experimental.session.export({ sessionID })
        return { data: exported.messages }
      },
    } },
  }
  return {
    api,
    async close() {
      controller.abort()
      for (const cleanup of cleanups.reverse()) if (typeof cleanup === "function") await cleanup()
    },
  }
}
