import { Effect } from "effect"
import { Commands } from "../../commands"
import { Runtime } from "../../../framework/runtime"
import { createClient, loadIntegrations, location, request } from "./shared"
import { AccountsRPC } from "../../../desktop-accounts-rpc.mjs"

export default Runtime.handler(
  Commands.commands.auth.commands["bridge-current"],
  Effect.fn("cli.auth.bridge-current")(function* () {
    const client = yield* createClient()
    yield* loadIntegrations(client)
    const value = yield* request((signal) => client.rpc(AccountsRPC).current({}, { location, signal }))
    process.stdout.write(JSON.stringify(value) + "\n")
  }),
)
