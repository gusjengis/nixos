import stale from "../../../tui-plugins/context-stale.tsx"
import { tuiBridge } from "../../tui-bridge.mjs"

export default {
  id: "desktop.context-stale",
  async setup(ctx) {
    const bridge = tuiBridge(ctx)
    try { await stale.tui(bridge.api) }
    catch (error) { await bridge.close(); throw error }
    return () => bridge.close()
  },
}
