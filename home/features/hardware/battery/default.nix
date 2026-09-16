# Battery monitoring.
#
# - `battery-notify` warns once when the battery falls to the threshold while
#   discharging. This used to be `scripts/battery-monitor.sh`, a
#   `while true; sleep 60` loop started from autostart.lua on every host,
#   including the desktops that have no battery at all. It is now a systemd
#   timer that only exists on laptops, so it survives a Hyprland restart, logs
#   to the journal, and can be inspected with
#   `systemctl --user status battery-notify.timer`.
# - `battery-history` appends the current battery level to a persistent log
#   every minute. It is gated on `laptop.enable` alone so it keeps running
#   without the desktop environment; the Quickshell battery chart reads this
#   log and therefore survives Hyprland/Quickshell restarts.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  batteryNotify = pkgs.writeShellApplication {
    name = "battery-notify";
    runtimeInputs = [ pkgs.libnotify ];
    text = builtins.readFile ./battery-notify.sh;
  };
  batteryHistory = pkgs.writeShellApplication {
    name = "battery-history";
    runtimeInputs = [ pkgs.coreutils pkgs.gawk ];
    text = builtins.readFile ./battery-history.sh;
  };
in
{
  config = lib.mkMerge [
    # Headless laptops have no notification daemon. This matches the old
    # behavior: the check was launched by Hyprland and therefore only ran in a
    # desktop session.
    (lib.mkIf (config.laptop.enable && config.desktopEnv.enable) {
      home.packages = [ batteryNotify ];

      systemd.user.services.battery-notify = {
        Unit.Description = "Warn when the battery is low";
        Service = {
          Type = "oneshot";
          ExecStart = lib.getExe batteryNotify;
        };
      };

      systemd.user.timers.battery-notify = {
        Unit.Description = "Check the battery level every minute";
        Timer = {
          OnStartupSec = "1m";
          OnUnitActiveSec = "1m";
          AccuracySec = "10s";
        };
        Install.WantedBy = [ "timers.target" ];
      };
    })

    # Runs regardless of the desktop session so the history log is written even
    # when Hyprland/Quickshell are not.
    (lib.mkIf config.laptop.enable {
      systemd.user.services.battery-history = {
        Unit.Description = "Record the current battery level";
        Service = {
          Type = "oneshot";
          ExecStart = lib.getExe batteryHistory;
        };
      };

      systemd.user.timers.battery-history = {
        Unit.Description = "Sample the battery level every minute";
        Timer = {
          OnStartupSec = "30s";
          OnUnitActiveSec = "1m";
          AccuracySec = "10s";
        };
        Install.WantedBy = [ "timers.target" ];
      };
    })
  ];
}