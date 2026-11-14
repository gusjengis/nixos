{ pkgs, legacy }:
let
  entry = pkgs.writeText "opencode-v2-policy-index.js" ''
    import legacy from "${legacy}"
    import { setupLegacyHooks } from "./legacy-hooks.mjs"
    export default {
      id: "desktop.session-policy",
      setup: (ctx) => setupLegacyHooks(ctx, legacy),
    }
  '';
in
pkgs.runCommand "opencode-v2-policy-compat" { } ''
  mkdir -p "$out"
  cp ${entry} "$out/index.js"
  cp ${./legacy-hooks.mjs} "$out/legacy-hooks.mjs"
''
