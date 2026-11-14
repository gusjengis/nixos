{
  config,
  pkgs,
  lib,
  repoRoot,
  ...
}:

let
  featureDir = "${repoRoot}/home/features/applications/handy";
  handy = pkgs.handy.overrideAttrs (old: {
    postPatch = (old.postPatch or "") + ''
      # Release virtual modifiers before wtype removes its keyboard. Hyprland
      # otherwise retains stale modifiers and stops matching dictation binds.
      substituteInPlace src-tauri/src/clipboard.rs \
        --replace-fail 'vec!["-M", "ctrl", "-k", "v"]' \
          'vec!["-M", "ctrl", "-k", "v", "-m", "ctrl"]' \
        --replace-fail 'vec!["-M", "shift", "-k", "Insert"]' \
          'vec!["-M", "shift", "-k", "Insert", "-m", "shift"]' \
        --replace-fail 'vec!["-M", "ctrl", "-M", "shift", "-k", "v"]' \
          'vec!["-M", "ctrl", "-M", "shift", "-k", "v", "-m", "shift", "-m", "ctrl"]'
    '';
  });
in
{
  config = lib.mkIf (config.desktopEnv.enable && config.personalDesktop.enable) {
    home.packages = [ handy ];

    # Only the settings file is versioned. The rest of
    # ~/.local/share/com.pais.handy is app data: recordings, models, history.db,
    # and WebKit caches, so the directory itself is not linked.
    home.file.".local/share/com.pais.handy/settings_store.json".source =
      config.lib.file.mkOutOfStoreSymlink "${featureDir}/settings_store.json";
  };
}
