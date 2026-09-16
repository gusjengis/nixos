{
  config,
  lib,
  pkgs,
  ...
}:

{
  options.gaming.enable = lib.mkEnableOption "gaming" // {
    default = false;
  };
  config = lib.mkIf (config.gaming.enable && config.desktopEnv.enable) {
    home.packages = with pkgs; [
      protonup-qt
      prismlauncher
      atlauncher
      lutris
      solitaire-tui
    ];
  };
}
