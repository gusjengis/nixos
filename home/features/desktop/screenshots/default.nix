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
      jq
      libnotify
      slurp
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
