import { Database } from "bun:sqlite"
import { Global } from "@opencode/util/global"
import { Effect } from "effect"
import { Commands } from "../../commands"
import { Runtime } from "../../../framework/runtime"
import { ServerConnection } from "../../../services/server-connection"
import { databasePath } from "../../../database-path"

export default Runtime.handler(
  Commands.commands.session.commands["compat-db"],
  Effect.fn("cli.session.compat-db")(function* (input) {
    // Native startup owns schema initialization and migrations. The temporary
    // compatibility view then preserves the existing atomic context-move SQL.
    yield* ServerConnection.resolve()
    const global = yield* Global.Service
    const rows = yield* Effect.try(() => {
      const db = new Database(databasePath(global.data), { readwrite: true, create: false })
      try {
        db.run("PRAGMA busy_timeout=5000")
        db.run("CREATE TEMP VIEW session AS SELECT * FROM main.session_v2")
        db.run(`CREATE TEMP TRIGGER context_metadata_update INSTEAD OF UPDATE OF metadata,time_updated ON session
          BEGIN UPDATE session_v2 SET metadata=NEW.metadata,time_updated=NEW.time_updated WHERE id=OLD.id; END`)
        return db.query(input.query).all()
      } finally { db.close() }
    })
    process.stdout.write(JSON.stringify(rows) + "\n")
  }),
)
