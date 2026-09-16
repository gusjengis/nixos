{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
  ];

  system.stateVersion = "25.11";
  dataDrive.client.enable = true;
  git.enable = true;
  grub.enable = true;
  hyprland.enable = false;
  nvidia.enable = true;
  nvim.enable = true;
  repo.networkmanager.enable = true;
  tailscale.enable = true;
  vial.enable = false;
  virtual-machines.enable = false;
}
