{ config, pkgs, ... }:
let
  configRoot = "${config.home.homeDirectory}/.home-manager/features/terminal/tmux";
  createTmuxSession = pkgs.writeShellApplication {
    name = "create-tmux-session";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.tmux
    ];
    text = ''
      exec bash "${configRoot}/create_tmux_session.sh" "$@"
    '';
  };

in
{
  home.packages = [
    pkgs.tmux
    createTmuxSession
  ];

  xdg.configFile = {
    "tmux/tmux.conf".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/tmux.conf";
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
