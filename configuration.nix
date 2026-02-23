{
  config,
  lib,
  inputs,
  pkgs,
  stable,
  ...
}:
{
  nvidia.enable = true;
  virtual-machines.enable = true;
  system.stateVersion = "25.05";
}
