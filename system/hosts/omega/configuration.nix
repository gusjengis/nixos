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
  nvim.enable = true;

  # Private git forge for the fleet, plus the nightly job that feeds the
  # wallpaper library it now holds. This is the fastest machine and already
  # serves the binary cache, so compute-shaped services belong here rather than
  # on alpha.
  forge.enable = true;
  wallpaperFetch.enable = true;

  # Synced copy of the Obsidian vault; normalizes raw captures into
  # Normalized/ with the resident model below.
  notesPipeline.enable = true;

  # Fleet inference host. The OpenCode auto-router on every other machine sends
  # each prompt here to be graded before it picks a paid model, and the nightly
  # wallpaper job asks it which part of the day each new image belongs to, and
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
  # ~4 KiB/token for the speculative draft head. Interactive OpenCode sessions
  # spend ~13k tokens on the system prompt, so 48k still leaves room to talk,
  # and the note pipeline never sends more than one page (~8k) per call.
  # 64k would leave no room for the retrieval embedder below.
  ollama.contextLength = 49152;

  # Note pipeline embedders (notes/EXTRACTION_PLAN.md), Jina v5 text-small.
  # Retrieval answers searches, by a person or by Qwen while linking, so it
  # sits on the GPU for latency. Text-matching (dedup, link shortlists) only
  # runs once per new thought in the background, so it costs no VRAM.
  ollama.embedders = {
    jina-v5-retrieval.from = "hf.co/jinaai/jina-embeddings-v5-text-small-retrieval-GGUF:Q8_0";
    jina-v5-matching = {
      from = "hf.co/jinaai/jina-embeddings-v5-text-small-text-matching-GGUF:Q8_0";
      cpu = true;
    };
  };

  repo.networkmanager.enable = true;
  tailscale.enable = true;
  virtual-machines.enable = false;
}
