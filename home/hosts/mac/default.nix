# Apple Silicon laptop running Asahi, with the full desktop.
#
# aarch64, so the native Discord and Slack packages are unavailable here and
# the webapp launchers stand in for them. See features/applications/communication.
{
  laptop.enable = true;

  desktopEnv.enable = true;
  dev.enable = true;
  gaming.enable = false;
  gameDev.enable = false;
  bambu.enable = false;
  windowsVm.enable = true;
}
