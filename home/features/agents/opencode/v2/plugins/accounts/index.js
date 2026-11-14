import { AccountsRPC } from "./rpc.mjs"

export function legacyOpenAI(value) {
  if (value?.type !== "oauth" || !value.metadata?.accountID)
    throw new Error("Current OpenAI connection is not a complete ChatGPT OAuth login")
  return { type: "oauth", access: value.access, refresh: value.refresh,
    expires: value.expires, accountId: value.metadata.accountID }
}

export default {
  id: "desktop.accounts",
  async setup(ctx) {
    await ctx.rpc.register(AccountsRPC, {
      current: async () => {
        const connection = await ctx.integration.connection.active("openai")
        if (!connection) throw new Error("OpenAI is not connected")
        // Native resolution owns refresh locking and write-back. The quota
        // widget calls this only when its selected credential needs renewal.
        return legacyOpenAI(await ctx.integration.connection.resolve(connection))
      },
    })
  },
}
