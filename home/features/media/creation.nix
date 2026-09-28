{
  config,
  pkgs,
  lib,
  ...
}:

{
  config = lib.mkMerge [
    (lib.mkIf config.desktopEnv.enable {
      home.packages = with pkgs; [
        obs-studio
      ];
    })
    (lib.mkIf (config.desktopEnv.enable && config.mediaEditing.enable) {
      home.packages = with pkgs; [
        audacity
        kdePackages.kdenlive
        gimp
      ];
    })
  ];
}
