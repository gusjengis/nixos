export default {
  id: "desktop.model-filter",
  async setup(ctx) {
    const provider = ctx.options.provider
    if (typeof provider !== "string" || !Array.isArray(ctx.options.models))
      throw new Error("Model filter requires a provider and model allowlist")
    const allowed = new Set(ctx.options.models)
    await ctx.model.transform((editor) => {
      for (const model of editor.list(provider)) if (!allowed.has(model.id)) editor.remove(provider, model.id)
    })
  },
}
