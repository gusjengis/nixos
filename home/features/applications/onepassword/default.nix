{
  config,
  pkgs,
  lib,
  ...
}:

{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ pkgs._1password-gui ];
  };

  # First installation requires signing into the GUI and browser extension.
}
