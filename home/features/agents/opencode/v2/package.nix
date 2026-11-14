{ opencode, system ? "x86_64-linux" }:
let
  pkgs = opencode.inputs.nixpkgs.legacyPackages.${system};
  dependencies = pkgs.callPackage "${opencode}/nix/node_modules.nix" ({
    rev = "dc2ffcf";
  } // pkgs.lib.optionalAttrs (system == "x86_64-linux") {
    hash = "sha256-s8XswivimwgzG0wMleHee5zliDKd+UC84eAvBvzr6cI=";
  });
in
(pkgs.callPackage "${opencode}/nix/opencode.nix" { node_modules = dependencies; }).overrideAttrs (old: {
  patches = (old.patches or [ ]) ++ [ ./model-carry.patch ./todo-title.patch ./context-sessions.patch ./agent-colors.patch ./legacy-transfer.patch ./history-picker.patch ./accounts.patch ./profile-roots.patch ./handoff.patch ];
  postPatch = old.postPatch + ''
    # Effect's server uses WebSocketServer; these two unused named exports
    # are absent from the pinned Bun 1.4.2 runtime and otherwise break startup.
    substituteInPlace packages/cli/script/build.ts \
      --replace-fail 'createWebSocketStream, extension, Receiver, Sender, subprotocol, WebSocket, WebSocketServer' \
                     'createWebSocketStream, Receiver, Sender, WebSocket, WebSocketServer'
    cp ${./test-model-carry.tsx} packages/tui/test/model-carry.test.tsx
    cp ${./test-todo-title.ts} packages/core/test/tool-todo-title.test.ts
    cp ${./test-context-sessions.ts} packages/core/test/desktop-context.test.ts
    cp ${../context-sessions.ts} packages/core/src/session/desktop-context.ts
    substituteInPlace packages/core/src/session/desktop-context.ts \
      --replace-fail '@opencode-ai/core/session/sql' './sql.js'
    cp ${../context-state.mjs} packages/core/src/session/context-state.mjs
    cp ${./agent-colors.mjs} packages/tui/src/util/desktop-agent-colors.mjs
    cp ${./legacy-transfer.ts} packages/core/src/session/legacy-transfer.ts
    cp ${./convert-v1.ts} packages/cli/src/commands/handlers/session/convert-v1.ts
    cp ${./compat-db.ts} packages/cli/src/commands/handlers/session/compat-db.ts
    cp ${./test-legacy-transfer.ts} packages/core/test/legacy-transfer.test.ts
    cp ${./desktop-history.tsx} packages/tui/src/component/desktop-history.tsx
    cp ${../context-view.ts} packages/tui/src/util/desktop-context.ts
    cp ${../context-state.mjs} packages/tui/src/util/context-state.mjs
    cp ${../history-controller.mjs} packages/tui/src/util/history-controller.mjs
    cp ${../history-client.mjs} packages/tui/src/util/history-client.mjs
    cp ${./test-desktop-history.tsx} packages/tui/test/desktop-history.test.tsx
    cp ${./auth-bridge-current.ts} packages/cli/src/commands/handlers/auth/bridge-current.ts
    cp ${./auth-bridge-select.ts} packages/cli/src/commands/handlers/auth/bridge-select.ts
    cp ${./plugins/accounts/rpc.mjs} packages/cli/src/desktop-accounts-rpc.mjs
    cp ${./migrate-v1.ts} packages/cli/src/commands/handlers/session/migrate-v1.ts
    cp ${./profile-handoff.mjs} packages/core/src/session/profile-handoff.mjs
  '';
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    (cd "$NIX_BUILD_TOP/source/packages/tui" && bun test test/model-carry.test.tsx)
    (cd "$NIX_BUILD_TOP/source/packages/tui" && bun test test/prompt-shell-failure.test.tsx test/prompt-cursor.test.tsx)
    (cd "$NIX_BUILD_TOP/source/packages/tui" && bun test test/desktop-history.test.tsx)
    (cd "$NIX_BUILD_TOP/source/packages/core" && bun test test/tool-todo-title.test.ts test/tool-todo.test.ts)
    (cd "$NIX_BUILD_TOP/source/packages/core" && bun test test/desktop-context.test.ts test/session-owned.test.ts test/session-list.test.ts)
    (cd "$NIX_BUILD_TOP/source/packages/core" && bun test test/legacy-transfer.test.ts)
    runHook postCheck
  '';
})
