# Recovery for the Apple Silicon HDMI link dropping mid-session.
#
# Specific to this machine: the M2 Pro DCP tears down its HDMI 2.1 FRL link
# under load ("FRL error rate exceeded"), and Hyprland does not re-modeset when
# it comes back, which stalls the whole session on 10 second flip_done
# timeouts. See display-recovery.sh for the full trace.
#
# Kept in hosts/mac rather than features/desktop/hyprland because no other host
# has a DCP.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  # Connectors driven by the DCP. eDP-1 is deliberately absent: the internal
  # panel is on a different DCP instance (389c00000) and does not hotplug.
  connectors = [ "HDMI-A-1" ];

  displayRecovery = pkgs.writeShellApplication {
    name = "display-recovery";
    runtimeInputs = [
      pkgs.coreutils # stdbuf, timeout, cat, sleep
      pkgs.systemd # udevadm
    ];
    text = builtins.readFile ./display-recovery.sh;
  };
in
{
  config = lib.mkIf config.desktopEnv.enable {
    # Also exposed on PATH so the state can be inspected or driven by hand.
    home.packages = [ displayRecovery ];

    systemd.user.services.display-recovery = {
      Unit = {
        Description = "Re-apply Hyprland monitor config after a DCP link teardown";
        PartOf = [ "graphical-session.target" ];
        After = [ "graphical-session.target" ];
      };

      Service = {
        # hyprctl comes from the Hyprland fork in home.packages, so the user
        # PATH is what should resolve it, not runtimeInputs.
        ExecStart = "${lib.getExe displayRecovery} ${lib.escapeShellArgs connectors}";
        # The udev stream should never end; if it does, the machine is left
        # without recovery, so come straight back.
        Restart = "always";
        RestartSec = 5;
      };

      Install.WantedBy = [ "graphical-session.target" ];
    };
  };
}
