{
  pkgs,
  inputs,
  repoRoot,
}:
let
  native = inputs.opencode.packages.${pkgs.stdenv.hostPlatform.system}.default.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [
      ./context-sessions.patch
      ./todo-title.patch
      ./model-carry.patch
    ];
    postPatch = (old.postPatch or "") + ''
      cp ${./context-sessions.ts} packages/opencode/src/session/context-sessions.ts
      cp ${./context-view.ts} packages/tui/src/util/desktop-context.ts
      cp ${./context-state.mjs} packages/opencode/src/session/context-state.mjs
      cp ${./context-state.mjs} packages/tui/src/util/context-state.mjs
      cp ${./history-controller.mjs} packages/tui/src/util/history-controller.mjs
      cp ${./history-client.mjs} packages/tui/src/util/history-client.mjs
      cp ${./desktop-history.tsx} packages/tui/src/component/desktop-history.tsx
      cp ${./test-todo-title.ts} packages/opencode/test/tool/todo-title.test.ts
    '';
    doCheck = true;
    checkPhase = ''
      runHook preCheck
      (cd "$NIX_BUILD_TOP/source/packages/opencode" && bun test test/tool/todo-title.test.ts)
      runHook postCheck
    '';
  });
  launcher = pkgs.writeShellApplication {
    name = "opencode";
    runtimeInputs = [
      pkgs.python3
      pkgs.tmux
    ];
    text = ''
      exec python3 -B "${repoRoot}/home/features/desktop/contexts/context_chat_library.py" launch ${native}/bin/opencode "$@"
    '';
  };
  chats = pkgs.writeShellApplication {
    name = "opencode-context-chats";
    runtimeInputs = [
      pkgs.python3
      launcher
    ];
    text = ''
      exec python3 -B "${repoRoot}/home/features/desktop/contexts/context_chat_library.py" "$@"
    '';
  };
in
{
  inherit native launcher chats;
}
