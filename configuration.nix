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
  # GTX 1080 graphics and HDMI audio; RTX 3090 remains available to NixOS.
  virtual-machines.vfioPciIds = [
    "10de:1b80"
    "10de:10f0"
  ];
  virtual-machines.fileSharing.enable = true;
  system.stateVersion = "25.05";
}
