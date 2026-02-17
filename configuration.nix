{
  config,
  lib,
  inputs,
  pkgs,
  stable,
  ...
}:
{
  steam.enable = true;
  nvidia.enable = true;
  virtual-machines.enable = true;

  system.stateVersion = "25.05";
}
