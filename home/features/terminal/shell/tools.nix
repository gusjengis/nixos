{ config, pkgs, ... }:

{
  home.packages = with pkgs; [
    fd
    skim
    jq
  ];

  programs.fzf = {
    enable = true;
    enableBashIntegration = true;
  };

  programs.direnv = {
    enable = config.dev.enable;
    enableBashIntegration = config.dev.enable;
    nix-direnv.enable = config.dev.enable;
    config.global.log_filter = "^$";
  };

  news.display = "silent";
}
