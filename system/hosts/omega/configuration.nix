{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./forgejo.nix
    ./nix_build_farm_server.nix
    ./wallpaper_fetch.nix
  ];

  system.stateVersion = "25.11";
  dataDrive.client.enable = true;
  git.enable = true;
  grub.enable = true;
  hyprland.enable = false;
  nvidia.enable = true;
  nvim.enable = true;

  # Private git forge for the fleet, plus the nightly job that feeds the
  # wallpaper library it now holds. This is the fastest machine and already
  # serves the binary cache, so compute-shaped services belong here rather than
  # on alpha.
  forge.enable = true;
  wallpaperFetch.enable = true;

  # Fleet inference host. The OpenCode auto-router on every other machine sends
  # each prompt here to be graded before it picks a paid model, and the nightly
  # wallpaper job asks it which part of the day each new image belongs to, so
  # this has to be the box with the 24 GB card on it.
  #
  # One model for both callers: qwen3.8:27b reads images as well as text, and
  # at 18 GB it is the largest Qwen that fits the card with room for its cache.
  # A second resident model would not fit beside it.
  ollama.enable = true;
  ollama.models = [ "qwen3.8:27b" ];
  ollama.preload = "qwen3.8:27b";

  repo.networkmanager.enable = true;
  tailscale.enable = true;
  virtual-machines.enable = false;
}
