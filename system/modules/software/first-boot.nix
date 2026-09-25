# Finishes an installation on the machine's first boot.
#
# Normal installations activate Home Manager before reboot. This service is a
# recovery path for interruption after NixOS was installed but before that
# activation completed. Its marker is removed by the installer on success.
#
# There is no enable option on purpose. The unit is inert on every machine that
# was not just installed, because it is conditioned on a file that only the
# installer writes. That also keeps it out of the installer's own role list.
{ pkgs, ... }:
let
  stateDir = "/var/lib/nixos-install";
  marker = "${stateDir}/pending-home-manager";
in
{
  systemd.services.nixos-first-boot = {
    description = "Finish the installer's Home Manager setup";

    after = [ "nix-daemon.service" ];
    wantedBy = [ "multi-user.target" ];

    # The marker holds the roster key to build. Its absence is what makes this
    # unit do nothing on every already-installed machine.
    unitConfig.ConditionPathExists = marker;

    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };

    path = with pkgs; [
      coreutils
      git
      nix
      openssh
    ];

    script = ''
      host="$(cat ${marker})"

      if [ -z "$host" ]; then
        echo "first-boot: ${marker} is empty; refusing to guess a host" >&2
        exit 1
      fi

      echo "first-boot: activating Home Manager for $host"

      # Failure leaves the marker in place, so the next boot retries rather
      # than silently leaving a machine with no user environment.
      ${pkgs.util-linux}/bin/runuser -u gusjengis -- \
        /etc/profiles/per-user/gusjengis/bin/home-manager switch \
        --flake "/etc/nixos#$host"

      rm -f ${marker}
      echo "first-boot: done"
    '';
  };

  # Autologin must not open a bare shell while recovery activation is still
  # linking the Bash configuration that starts Hyprland on tty1.
  systemd.services."getty@tty1" = {
    overrideStrategy = "asDropin";
    after = [ "nixos-first-boot.service" ];
  };
}
