import { Effect, Schema } from "effect"
import { Global } from "@opencode/util/global"
import path from "node:path"
import { Commands } from "../../commands"
import { Runtime } from "../../../framework/runtime"
import { createClient, request } from "./shared"

const Legacy = Schema.Struct({ type: Schema.Literal("oauth"), access: Schema.String,
  refresh: Schema.String, expires: Schema.Number, accountId: Schema.String })

export default Runtime.handler(
  Commands.commands.auth.commands["bridge-select"],
  Effect.fn("cli.auth.bridge-select")(function* (input) {
    const global = yield* Global.Service
    const data = process.env.OPENCODE_LEGACY_DATA_HOME ?? path.join(global.home, ".local/share")
    const saved = yield* Effect.tryPromise(() => Bun.file(path.join(data, "quickshell/ai-accounts", input.profile + ".json")).json())
    const auth = yield* Schema.decodeUnknownEffect(Legacy)(saved.auth)
    const client = yield* createClient()
    const credentials = yield* request((signal) => client.credential.list({ signal }))
    const id = "cred_quickshell_" + input.profile
    const value = { type: "oauth" as const, methodID: "chatgpt-browser", access: auth.access,
      refresh: auth.refresh, expires: auth.expires, metadata: { accountID: auth.accountId } }
    const label = "OpenAI · " + (input.profile === "personal" ? "Personal" : "Business")
    if (credentials.some((entry) => entry.id === id)) {
      yield* request((signal) => client.credential.update({ credentialID: id, label, value }, { signal }))
      yield* request((signal) => client.credential.activate({ credentialID: id }, { signal }))
    } else {
      yield* request((signal) => client.credential.create({ id, integrationID: "openai", label, value, activate: true }, { signal }))
    }
    process.stdout.write(JSON.stringify({ ok: true, profile: input.profile }) + "\n")
  }),
)
