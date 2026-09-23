# Apple Silicon laptop running Asahi, with the full desktop.
#
# aarch64, so the native Discord and Slack packages are unavailable here and
# the webapp launchers stand in for them. See features/applications/communication.
{
  imports = [ ./display-recovery.nix ];

  laptop.enable = true;

  desktopEnv.enable = true;
  # Hardware capability marker consumed by Quickshell. Other hosts have no
  # marker, so their fullscreen and bar behavior stays unchanged.
  xdg.dataFile."quickshell/notch-monitor".text = "eDP-1\n";
  dev.enable = true;
  gaming.enable = false;
  gameDev.enable = false;
  bambu.enable = false;
  windowsVm.enable = true;
}
