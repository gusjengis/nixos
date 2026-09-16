{
  config,
  pkgs,
  lib,
  ...
}:
let
  # Single source of truth for the OG VM lives with its RDP launcher, in
  # features/remote/windows-vm. The bookmark and the launcher must agree.
  og = config.windowsVm.og;

  tailnetThunarBookmarks = pkgs.writeShellApplication {
    name = "tailnet-thunar-bookmarks";
    runtimeInputs = with pkgs; [
      coreutils
      diffutils
      glib
      gnugrep
      jq
      netcat-openbsd
      tailscale
      util-linux
    ];
    text = builtins.readFile ./tailnet-thunar-bookmarks.sh;
  };
in
{
  home.packages = [ tailnetThunarBookmarks ];

  systemd.user.services.tailnet-thunar-bookmarks = {
    Unit = {
      Description = "Keep Thunar Tailnet bookmarks current";
      After = [ "default.target" ];
    };

    Service = {
      Type = "simple";
      ExecStart = "${lib.getExe tailnetThunarBookmarks} watch";
      Restart = "always";
      RestartSec = 5;
      Environment = [
        "TAILNET_THUNAR_PROBE_TIMEOUT=3"
        "TAILNET_THUNAR_REFRESH_INTERVAL=5"
        "TAILNET_THUNAR_FULL_REFRESH_INTERVAL=60"
        "TAILNET_THUNAR_OFFICE_GATEWAY=mac.tail29bd65.ts.net"
        "TAILNET_THUNAR_OG_HOST=${lib.last (lib.splitString "@" og.startHost)}"
        "TAILNET_THUNAR_OG_ADDRESS=${og.address}"
        "TAILNET_THUNAR_OG_SHARE=${og.smbShare}"
        "TAILNET_THUNAR_OG_USER=${og.user}"
      ];
    };

    Install.WantedBy = [ "default.target" ];
  };
}
