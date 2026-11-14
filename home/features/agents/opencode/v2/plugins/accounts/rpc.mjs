export const AccountsRPC = {
  id: "desktop.accounts",
  methods: {
    current: {
      input: { type: "object", additionalProperties: false },
      output: { type: "object", properties: {
        type: { const: "oauth" }, access: { type: "string" }, refresh: { type: "string" },
        expires: { type: "number" }, accountId: { type: "string" },
      }, required: ["type", "access", "refresh", "expires", "accountId"], additionalProperties: false },
    },
  },
  events: {},
}
