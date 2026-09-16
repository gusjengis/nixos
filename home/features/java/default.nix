{
  config,
  pkgs,
  lib,
  ...
}:

{
  config = lib.mkIf (config.desktopEnv.enable && (config.gaming.enable || config.dev.enable)) {
    home.packages = [ pkgs.zulu17 ];
  };
}
