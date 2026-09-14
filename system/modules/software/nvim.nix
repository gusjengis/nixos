{
  config,
  pkgs,
  lib,
  ...
}:

{
  options = {
    nvim.enable = lib.mkEnableOption "enables nvim";
  };

  config = lib.mkIf config.nvim.enable {

    environment.systemPackages = with pkgs; [
      neovim

      # Neovim's own runtime needs.
      wl-clipboard # "+y and "+p
      ripgrep # telescope live_grep
      fzf
      gcc # builds tree-sitter parsers and telescope-fzf-native
      gnumake
      nodejs_24

      # Baseline language tooling, deliberately small. Per-project servers and
      # formatters belong in that project's flake devShell, which direnv hands
      # to Neovim (see lua/direnv.lua in the config). What stays here is only
      # what has to work in any directory, with no project around it: editing
      # this configuration and stray Nix and Lua files.
      #
      # Nothing installs language servers at runtime any more. Mason used to,
      # and because its downloads live in ~/.local/share/nvim and no lockfile
      # covers them, every machine ended up with a different set - including a
      # `nil` that failed to build here because the rustup shim had no
      # toolchain.
      nil # Nix LSP
      nixfmt
      lua-language-server
      stylua
    ];

  };
}
