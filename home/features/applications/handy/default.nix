{
  config,
  pkgs,
  lib,
  repoRoot,
  ...
}:

let
  featureDir = "${repoRoot}/home/features/applications/handy";
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ pkgs.handy ];

    # Only the settings file is versioned. The rest of
    # ~/.local/share/com.pais.handy is app data: recordings, models, history.db,
    # and WebKit caches, so the directory itself is not linked.
    home.file.".local/share/com.pais.handy/settings_store.json".source =
      config.lib.file.mkOutOfStoreSymlink "${featureDir}/settings_store.json";
  };
}
