{
  config,
  pkgs,
  lib,
  ...
}:

{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = with pkgs; [
      obs-studio
      audacity
      kdePackages.kdenlive
      gimp
    ];
  };
}
