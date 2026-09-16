{ pkgs, ... }:

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
    enable = true;
    enableBashIntegration = true;
    nix-direnv.enable = true;
    config.global.log_filter = "^$";
  };

  news.display = "silent";
}
