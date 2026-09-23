# Finishes an installation on the machine's first boot.
#
# The installer builds the Home Manager closure into the new system's store
# while it still has a working nix-daemon on the ISO, so nothing here has to
# compile anything; activation is a matter of linking a profile that is already
# present. It is deferred to first boot rather than done in a chroot because
# activation wants a normal session: a running daemon, a real user, and an
# initialised per-user profile. Doing that inside `nixos-enter` works until it
# does not, and a half-activated profile is a bad thing to hand someone.
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

    # Home Manager reads flake inputs, and the secrets checkout the installer
    # placed in the home directory is only useful once the network is up.
    after = [
      "network-online.target"
      "nix-daemon.service"
    ];
    wants = [ "network-online.target" ];
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
}
