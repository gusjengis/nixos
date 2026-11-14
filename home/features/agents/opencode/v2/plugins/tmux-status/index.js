import { TmuxStatusPlugin } from "../../../plugins/tmux-status.js"
import { subscribeLegacyEvents } from "../../events.mjs"

export default {
  id: "desktop.tmux-status",
  async setup(ctx) {
    return subscribeLegacyEvents(ctx, await TmuxStatusPlugin())
  },
}
