import { convertLegacyTransfer } from "../../../../../core/src/session/legacy-transfer.js"
import { Effect } from "effect"
import { Commands } from "../../commands"
import { Runtime } from "../../../framework/runtime"

export default Runtime.handler(
  Commands.commands.session.commands["convert-v1"],
  Effect.fn("cli.session.convert-v1")(function* (input) {
    const data = yield* Effect.tryPromise(() => Bun.file(input.file).json())
    const converted = yield* Effect.try(() => convertLegacyTransfer(data))
    process.stdout.write(JSON.stringify(converted) + "\n")
  }),
)
