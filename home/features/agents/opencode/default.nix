{
  config,
  pkgs,
  lib,
  inputs,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/agents/opencode";
  hyprlandPackages = inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system};
  sessionNotify = pkgs.writeShellApplication {
    name = "opencode-session-notify";
    runtimeInputs = lib.optional config.desktopEnv.enable hyprlandPackages.hyprland ++ [
      inputs.opencode.packages.${pkgs.stdenv.hostPlatform.system}.default
      pkgs.glib
      pkgs.jq
      pkgs.kitty
      pkgs.libnotify
      pkgs.tmux
      pkgs.util-linux
    ];
    text = ''
      exec bash "${configRoot}/session-notify/session-notify-handler.sh" "$@"
    '';
  };
in
{
  # Pinned to the upstream flake rather than pkgs.opencode, which trails behind.
  # The tag lives in flake.nix; bump it there.
  home.packages = [
    inputs.opencode.packages.${pkgs.stdenv.hostPlatform.system}.default
    sessionNotify
  ];

  programs.bash.shellAliases.oc = "opencode";

  # Settings and plugins are linked back into this repository so edits apply on
  # the next OpenCode start, and so state OpenCode writes itself (recent models,
  # UI preferences) is versioned and synced to other machines.
  xdg.configFile = {
    "opencode/opencode.json".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/opencode.json";
    "opencode/tui.json".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/tui.json";
    "opencode/plugins/session-notify.js".source =
      config.lib.file.mkOutOfStoreSymlink "${configRoot}/session-notify/session-notify.js";
    "opencode/plugins/tmux-status.js".source =
      config.lib.file.mkOutOfStoreSymlink "${configRoot}/plugins/tmux-status.js";
    "opencode/tui-plugins/tmux-theme.js".source =
      config.lib.file.mkOutOfStoreSymlink "${configRoot}/tui-plugins/tmux-theme.js";

    # Caveman skill suite (caveman, caveman-commit, caveman-review, ...).
    # OpenCode scans ~/.config/opencode/skills recursively for **/SKILL.md, so
    # linking the whole skills dir picks up every sub-skill.
    # Update to latest: nix flake update caveman && rehome
    "opencode/skills/caveman-suite".source = "${inputs.caveman}/skills";

    # Caveman's OpenCode installer makes Caveman default-on by adding this
    # always-loaded rule file. Source it from the pinned flake input instead of
    # running the installer, so the behavior is reproducible through Home Manager.
    "opencode/AGENTS.md".text = ''
      <!-- caveman-begin -->
      ${builtins.readFile "${inputs.caveman}/src/rules/caveman-activate.md"}
      <!-- caveman-end -->
    '';
  };

  # OpenCode saves state by atomically replacing files, which breaks individual
  # symlinks. Link the directory instead; only model.json and kv.json are
  # tracked, while locks and prompt history are ignored beside them.
  home.file.".local/state/opencode" = {
    source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/state";
    force = true;
  };

  # Home Manager cannot replace a real directory with a directory symlink.
  # Preserve any pre-migration state, copy files not already present into the
  # repository's state directory, then let linkGeneration create the symlink.
  # The renamed backup stays beside the target for manual inspection/removal.
  home.activation.opencodeMigrateState = lib.hm.dag.entryBefore [ "linkGeneration" ] ''
    stateTarget="$HOME/.local/state/opencode"
    if [[ -d "$stateTarget" && ! -L "$stateTarget" ]]; then
      stateBackup="$stateTarget.pre-home-manager-$(date +%Y%m%d%H%M%S)"
      mv "$stateTarget" "$stateBackup"
      cp -an "$stateBackup/." "${configRoot}/state/"
    fi
  '';
}
