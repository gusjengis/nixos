{
  config,
  pkgs,
  lib,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/terminal/tmux";
  createTmuxSession = pkgs.writeShellApplication {
    name = "create-tmux-session";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.direnv
      pkgs.tmux
    ];
    text = ''
      exec bash "${configRoot}/create_tmux_session.sh" "$@"
    '';
  };
  taCmd = pkgs.writeShellApplication {
    name = "ta";
    runtimeInputs = [ pkgs.tmux ];
    text = ''
      tmux attach || tmux
    '';
  };
in
{
  # Every Home Manager runtime dependency receives the same native server barrier.
  nixpkgs.overlays = [ (final: prev: { tmux = import ./package.nix { pkgs = prev; }; }) ];
  home.packages = [
    pkgs.tmux
    taCmd
  ]
  ++ lib.optional (config.dev.enable || config.desktopContexts.enable) createTmuxSession;

  xdg.configFile = {
    "tmux/tmux.conf".source = config.lib.file.mkOutOfStoreSymlink (
      if config.desktopContexts.enable then "${configRoot}/tmux.conf" else "${configRoot}/tmux-basic.conf"
    );
    "tmux/github_dark.tmux".source =
      config.lib.file.mkOutOfStoreSymlink "${configRoot}/github_dark.tmux";
    "tmux/plugins".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/plugins";
    "tmux/create_tmux_session.sh".source =
      config.lib.file.mkOutOfStoreSymlink "${configRoot}/create_tmux_session.sh";
    "tmux/open_github.sh".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/open_github.sh";
    "tmux/tmux_jobs.sh".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/tmux_jobs.sh";
    "tmux/tmux_session_dispensary.sh".source =
      config.lib.file.mkOutOfStoreSymlink "${configRoot}/tmux_session_dispensary.sh";
  };
}
