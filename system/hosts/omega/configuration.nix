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

  # Fleet inference host. The OpenCode auto-router on every other machine sends
  # each prompt here to be graded before it picks a paid model, so this has to
  # be the box with the idle 24 GB card on it.
  ollama.enable = true;
  ollama.models = [ "qwen3:4b-instruct-2507-q8_0" ];
  ollama.preload = "qwen3:4b-instruct-2507-q8_0";

  repo.networkmanager.enable = true;
  tailscale.enable = true;
  vial.enable = false;
  virtual-machines.enable = false;
}
