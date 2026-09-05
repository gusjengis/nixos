{
  config,
  lib,
  inputs,
  pkgs,
  stable,
  ...
}:
{
  imports = [ ./windows-vm.nix ];

  nvidia.enable = true;
  virtual-machines.enable = true;
  system.stateVersion = "25.05";
}
