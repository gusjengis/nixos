{
  config,
  pkgs,
  lib,
  ...
}:

{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [
      pkgs._1password-gui
      pkgs._1password-cli
    ];
  };

  # First installation requires signing into the GUI and browser extension.
}
