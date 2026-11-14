{ pkgs }:
let
  legacy = import ../peripheral-plugins.nix { inherit pkgs; };
  entry = pkgs.writeText "opencode-v2-notify-index.js" ''
    import { $ } from "bun"
    import { SessionNotifyPlugin } from "${legacy}/session-notify.js"
    import { subscribeLegacyEvents } from "./events.mjs"
    export default {
      id: "desktop.session-notify",
      async setup(ctx) {
        const hooks = await SessionNotifyPlugin({ $, directory: ctx.location.directory })
        return subscribeLegacyEvents(ctx, hooks)
      },
    }
  '';
in
pkgs.runCommand "opencode-v2-session-notify" { } ''
  mkdir -p "$out"
  cp ${entry} "$out/index.js"
  cp ${./events.mjs} "$out/events.mjs"
''
