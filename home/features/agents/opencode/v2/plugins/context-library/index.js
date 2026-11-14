import { ContextLibraryPlugin } from "../../../plugins/context-library.js"
import { ContextLibraryRPC } from "./rpc.mjs"

export async function setupLibrary(ctx, factory = ContextLibraryPlugin) {
  const registration = await ctx.rpc.register(ContextLibraryRPC, {})
  const client = {
    session: { get: async ({ path }) => ({ data: await ctx.session.get({ sessionID: path.id }) }) },
    tui: { showToast: ({ body }) => registration.events.emit("notice", body) },
  }
  const hooks = await factory({ client })
  return async () => { await hooks.event?.({ event: { type: "server.instance.disposed" } }) }
}

export default { id: "desktop.context-library", setup: (ctx) => setupLibrary(ctx) }
