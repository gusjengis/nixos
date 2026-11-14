{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./forgejo.nix
    ./nix_build_farm_server.nix
    ./wallpaper_fetch.nix
    ./notes.nix
  ];

  system.stateVersion = "25.11";
  dataDrive.client.enable = true;
  git.enable = true;
  grub.enable = true;
  hyprland.enable = false;
  nvidia.enable = true;
  gpu-unlock.enable = true;
  nvim.enable = true;

  # Private git forge for the fleet, plus the nightly job that feeds the
  # wallpaper library it now holds. This is the fastest machine and already
  # serves the binary cache, so compute-shaped services belong here rather than
  # on alpha.
  forge.enable = true;
  wallpaperFetch.enable = true;

  # Synced copy of the Obsidian vault; disabled — it needed the Jina v5
  # embedders that no longer reside here. Re-enable with ollama.embedders.
  notesPipeline.enable = false;

  # Fleet inference host. The nightly wallpaper job asks it which part of the
  # day each new image belongs to, and
  # the Supernote OCR on alpha and the note normalizer (notes.nix) use it too,
  # so this has to be the box with the 24 GB card on it.
  #
  # One chat model for every caller: qwen3.8:27b reads images as well as text,
  # and at 18 GB it is the largest Qwen that fits the card with room for its
  # cache. A second resident chat model would not fit beside it.
  ollama.enable = true;
  ollama.models = [ "qwen3.8:27b" ];
  ollama.preload = "qwen3.8:27b";
  # Only 16 of qwen3.8's 65 layers carry a KV cache: ~64 KiB/token at f16, plus
  # ~4 KiB/token for the speculative draft head. The old 48k cap left the GPU
  # room for the retrieval embedder; that embedder is gone now, so the freed
  # ~1.5 GB grows the cache to 64k with headroom to spare.
  ollama.contextLength = 65536;

  repo.networkmanager.enable = true;
  tailscale.enable = true;
  virtual-machines.enable = false;
}
