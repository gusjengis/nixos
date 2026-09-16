{
  config,
  pkgs,
  lib,
  ...
}:

{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = with pkgs; [
      vlc
      pavucontrol
      playerctl
      wireplumber
    ];
  };
}
