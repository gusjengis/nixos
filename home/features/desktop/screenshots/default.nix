{
  config,
  pkgs,
  lib,
  ...
}:
let
  takeScreenshot = pkgs.writeShellApplication {
    name = "take-screenshot";
    runtimeInputs = with pkgs; [
      grim
      imagemagick
      jq
      libnotify
      slurp
      swappy
      wl-clipboard
    ];
    text = builtins.readFile ./take-screenshot.sh;
  };
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ takeScreenshot ];
  };
}
