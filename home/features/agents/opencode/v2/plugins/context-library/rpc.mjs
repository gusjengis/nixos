export const ContextLibraryRPC = {
  id: "desktop.context-library",
  methods: {},
  events: {
    notice: { schema: {
      type: "object", properties: {
        title: { type: "string" }, message: { type: "string" },
        variant: { type: "string", enum: ["info", "success", "warning", "error"] },
      }, required: ["title", "message", "variant"], additionalProperties: false,
    } },
  },
}
