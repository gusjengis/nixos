import { Effect } from "effect"
import { Commands } from "../../commands"
import { Runtime } from "../../../framework/runtime"
import { createClient, request } from "../auth/shared"

export default Runtime.handler(
  Commands.commands.session.commands["migrate-v1"],
  Effect.fn("cli.session.migrate-v1")(function* () {
    const client = yield* createClient()
    while (true) {
      const status = yield* request((signal) => client.experimental.migration.v1.status({ signal }))
      if (status.status === "completed") {
        process.stdout.write(JSON.stringify(status) + "\n")
        return
      }
      if (status.status === "error") return yield* Effect.fail(new Error(status.error))
      yield* Effect.sleep("250 millis")
    }
  }),
)
