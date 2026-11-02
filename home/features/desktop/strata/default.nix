{
  config,
  lib,
  pkgs,
  repoRoot,
  ...
}:
{
  config = {
    home.packages = lib.optionals config.desktopEnv.enable [ pkgs.strata ];

    xdg.dataFile."applications/io.github.lgse.Strata.desktop" = lib.mkIf config.desktopEnv.enable {
      source = config.lib.file.mkOutOfStoreSymlink "${repoRoot}/home/features/desktop/strata/finder.desktop";
    };

    xdg.configFile."strata".source =
      config.lib.file.mkOutOfStoreSymlink "${repoRoot}/home/features/desktop/strata/config";

    home.activation.strataMigrateConfig = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
      config_dir=${lib.escapeShellArg "${config.xdg.configHome}/strata"}
      repo_config=${lib.escapeShellArg "${repoRoot}/home/features/desktop/strata/config"}
      if [ -d "$config_dir" ] && [ ! -L "$config_dir" ]; then
        backup="$config_dir.before-nix-$(date +%Y%m%d%H%M%S)"
        mv -T -- "$config_dir" "$backup"
        if [ -f "$backup/tabs.toml" ] && [ ! -e "$repo_config/tabs.toml" ]; then
          cp -- "$backup/tabs.toml" "$repo_config/tabs.toml"
        fi
      fi
    '';
  };
}
