import persistence from "../../../tui-plugins/context-persistence.js"
import { tuiBridge } from "../../tui-bridge.mjs"

export default {
  id: "desktop.context-persistence",
  async setup(ctx) {
    if (!process.env.OPENCODE_DB) throw new Error("Context persistence requires the local V2 launcher with an explicit database.")
    const bridge = tuiBridge(ctx)
    try { await persistence.tui(bridge.api) }
    catch (error) { await bridge.close(); throw error }
    return () => bridge.close()
  },
}
