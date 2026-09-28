{
  config,
  pkgs,
  lib,
  ...
}:

{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = with pkgs; [
      pavucontrol
      playerctl
      wireplumber
    ];
  };
}
