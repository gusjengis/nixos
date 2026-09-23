# Facts read straight out of a committed `facter.json`, with no NixOS module
# system involved.
#
# `system/modules/hardware/facter-policy.nix` already derives hardware defaults
# for NixOS, but two consumers cannot use it:
#
#   * Home Manager is standalone here, so it never evaluates a NixOS
#     configuration and cannot read `config.repo.hardware.detected`.
#   * The installer needs the same answers before any configuration for the new
#     machine exists at all.
#
# Both of those call in here instead, so portable-hardware detection has one
# definition rather than three that can drift apart.
{ lib }:
let
  # SMBIOS 3.7.0 table 17: portable form factors.
  portableChassisTypes = [
    8 # Portable
    9 # Laptop
    10 # Notebook
    11 # Hand Held
    14 # Sub Notebook
    30 # Tablet
    31 # Convertible
    32 # Detachable
  ];
in
rec {
  inherit portableChassisTypes;

  # `hardware.system.form_factor` reports "laptop" on every machine in this
  # fleet, including the desktops, so it cannot be used for this. The SMBIOS
  # chassis type can: the desktops report 3, the ThinkPads report 10.
  #
  # Machines with no SMBIOS table at all (Apple Silicon) report no chassis and
  # therefore read as non-portable. `mac` sets `laptop.enable` explicitly for
  # exactly that reason.
  isPortable =
    report:
    lib.any (entry: lib.elem (entry.chassis_type.value or 0) portableChassisTypes) (
      report.smbios.chassis or [ ]
    );

  readReport =
    path: if builtins.pathExists path then builtins.fromJSON (builtins.readFile path) else { };

  isPortableHost =
    hostsDir: hostName: isPortable (readReport (hostsDir + "/${hostName}/facter.json"));
}
