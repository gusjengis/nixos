{
  config,
  pkgs,
  lib,
  ...
}:
let
  repoRoot = "${config.home.homeDirectory}/.home-manager";
  featureDir = "${repoRoot}/features/development/nvim";
  configDir = "${featureDir}/config";

  # The config is a submodule, so a Home Manager generation pins an exact
  # Neovim config commit. It is still its own repository with its own remote:
  # it opens as its own project in tmux and the launcher, and is committed in
  # directly.
  syncConfig = pkgs.writeShellApplication {
    name = "nvim-config-sync";
    runtimeInputs = with pkgs; [
      coreutils
      git
    ];
    text = ''
      export HM_REPO=${repoRoot}
      export NVIM_CONFIG_SUBMODULE=features/development/nvim/config
      ${builtins.readFile ./sync-config.sh}
    '';
  };

  # Plugins are machine-local git clones under ~/.local/share/nvim. Nothing
  # reconciles them with lazy-lock.json on its own: lazy applies the lock on a
  # fresh install or on an explicit restore, and `:Lazy update` moves off it.
  # That is exactly how one machine ended up on nvim-treesitter's main branch,
  # whose removed parsers API broke Telescope's preview. Restoring on every
  # deployment makes the lockfile authoritative everywhere, and cleaning
  # removes clones the spec no longer lists.
  syncPlugins = pkgs.writeShellApplication {
    name = "nvim-plugin-sync";
    runtimeInputs = with pkgs; [
      coreutils
      git
      jq
    ];
    text = ''
      nvim_bin="$(command -v nvim || echo /run/current-system/sw/bin/nvim)"
      [ -x "$nvim_bin" ] || { echo "nvim-plugin-sync: no nvim on PATH" >&2; exit 0; }

      lock="$HOME/.config/nvim/lazy-lock.json"
      lazy_dir="$HOME/.local/share/nvim/lazy"

      restore() {
        "$nvim_bin" --headless "+Lazy! restore" "+Lazy! clean" +qa >/dev/null 2>&1
      }

      mismatched() {
        ${pkgs.jq}/bin/jq -r 'to_entries[] | [.key, .value.commit] | @tsv' "$lock" \
          | while IFS=$'\t' read -r plugin expected; do
              path="$lazy_dir/$plugin"
              actual="$(${pkgs.git}/bin/git -C "$path" rev-parse HEAD 2>/dev/null || true)"
              if [[ "$actual" != "$expected" ]]; then
                printf '%s\t%s\t%s\n' "$plugin" "''${actual:-missing}" "$expected"
              fi
            done
      }

      restore || true

      # Lazy refuses to update a clone with local changes. Plugin directories
      # are caches, not working repositories; if one is still at the wrong
      # commit after restore, replace that cache and let Lazy reinstall it.
      while IFS=$'\t' read -r plugin _actual _expected; do
        [[ -n "$plugin" ]] && rm -rf "$lazy_dir/$plugin"
      done < <(mismatched)

      restore || true

      remaining="$(mismatched)"
      if [[ -n "$remaining" ]]; then
        echo "nvim-plugin-sync: plugins still differ from lazy-lock.json:" >&2
        echo "$remaining" >&2
        exit 1
      fi

      # Mason's downloads are unpinned, machine-local binaries; the config no
      # longer uses it, so its data directory is stale cache.
      if [ ! -d "$HOME/.local/share/nvim/lazy/mason.nvim" ]; then
        rm -rf "$HOME/.local/share/nvim/mason"
      fi

      # Interrupted installs leave <plugin>.cloning directories behind, which
      # `Lazy! clean` does not consider its own.
      rm -rf "$HOME"/.local/share/nvim/lazy/*.cloning
    '';
  };
in
{
  home.packages = [
    syncConfig
    syncPlugins
  ];

  # Linked as a whole directory: lazy-lock.json and any new file the config
  # gains need no Nix change, and writes from Neovim land in the repository.
  xdg.configFile."nvim" = {
    source = config.lib.file.mkOutOfStoreSymlink configDir;
    force = true;
  };

  # A fresh clone of this repository has an empty submodule directory, and a
  # pulled pointer change needs checking out, both before the link is made.
  home.activation.nvimConfigSync = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
    ${lib.getExe syncConfig} || true
  '';

  # Home Manager's `force` cannot replace a real directory with a symlink, and
  # every machine still has the standalone clone that used to live here.
  home.activation.nvimMigrateToSymlink = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
    nvimTarget="$HOME/.config/nvim"
    if [[ -e "$nvimTarget" && ! -L "$nvimTarget" ]]; then
      backup="$nvimTarget.pre-submodule"
      if [[ -e "$backup" ]]; then
        backup="$backup.$(date +%s)"
      fi
      echo "moving pre-submodule Neovim config to $backup"
      mv "$nvimTarget" "$backup"
    fi
  '';

  # After the config is linked, so the restore reads the deployed lockfile.
  home.activation.nvimPluginSync = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    if [[ -z "''${HM_SKIP_NVIM_SYNC:-}" ]]; then
      ${lib.getExe syncPlugins}
    fi
  '';
}
