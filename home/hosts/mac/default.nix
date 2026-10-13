# Apple Silicon laptop running Asahi, with the full desktop.
#
# aarch64, so the native Discord and Slack packages are unavailable here and
# the webapp launchers stand in for them. See features/applications/communication.
{ pkgs, ... }:

let
  lidState = pkgs.writeShellApplication {
    name = "lid-state";
    runtimeInputs = [ pkgs.evtest ];
    text = ''
      status=0
      evtest --query /dev/input/by-path/platform-macsmc-input-event EV_SW SW_LID >/dev/null || status=$?
      case "$status" in
        0) printf 'open\n' ;;
        10) printf 'closed\n' ;;
        *) exit "$status" ;;
      esac
    '';
  };
in
{
  imports = [ ./display-recovery.nix ];

  laptop.enable = true;
  home.packages = [ lidState ];

  desktopEnv.enable = true;
  # Hardware capability marker consumed by Quickshell. Other hosts have no
  # marker, so their fullscreen and bar behavior stays unchanged.
  xdg.dataFile."quickshell/notch-monitor".text = "eDP-1\n";
  dev.enable = true;
  gaming.enable = false;
  bambu.enable = false;
  windowsVm.enable = true;
}
