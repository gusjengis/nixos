{
  pkgs,
  inputs,
  repoRoot,
}:
let
  native = inputs.opencode.packages.${pkgs.stdenv.hostPlatform.system}.default.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [ ./context-sessions.patch ];
    postPatch = (old.postPatch or "") + ''
      cp ${./context-sessions.ts} packages/opencode/src/session/context-sessions.ts
      cp ${./context-view.ts} packages/tui/src/util/desktop-context.ts
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
  inherit launcher chats;
}
