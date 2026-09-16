{
  config,
  lib,
  repoRoot,
  ...
}:

let
  featureDir = "${repoRoot}/home/features/desktop/webapps";

  liveLink = path: config.lib.file.mkOutOfStoreSymlink "${featureDir}/${path}";

  readNames = dir: builtins.attrNames (builtins.readDir (./. + "/${dir}"));

  isWebapp = name: lib.hasPrefix "webapp-" name;

  # ~/.local/share/applications and the icon directory are shared with Steam,
  # Lutris, wine, and Home Manager itself, so these are per-file links. A
  # directory link would take the whole directory away from them.
  entryLink = name: {
    name = "applications/${name}";
    value = {
      source = liveLink "applications/${name}";
    };
  };

  iconLink = name: {
    name = "icons/hicolor/128x128/apps/${name}";
    value = {
      source = liveLink "icons/${name}";
    };
  };

  allEntries = readNames "applications";
  allIcons = readNames "icons";

  # Entries naming a real local program stay deployed on every host, because
  # features/files/default-apps/mimeapps.list names them as handlers. Only the
  # webapps follow the desktop environment, which is what the old linker did by
  # unlinking webapp-*.desktop when the desktop was disabled.
  alwaysEntries = builtins.filter (name: !isWebapp name) allEntries;
  alwaysIcons = builtins.filter (name: !isWebapp name) allIcons;
  desktopEntries = builtins.filter isWebapp allEntries;
  desktopIcons = builtins.filter isWebapp allIcons;
in
{
  config = lib.mkMerge [
    {
      xdg.dataFile = builtins.listToAttrs ((map entryLink alwaysEntries) ++ (map iconLink alwaysIcons));
    }

    (lib.mkIf config.desktopEnv.enable {
      xdg.dataFile = builtins.listToAttrs ((map entryLink desktopEntries) ++ (map iconLink desktopIcons));

      # GTK resolves Icon= names through the hicolor theme, which needs an
      # index.theme and a refreshed cache to be picked up.
      home.activation.webappIconCache = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
        icon_dir="$HOME/.local/share/icons/hicolor"
        mkdir -p "$icon_dir"

        if [ ! -e "$icon_dir/index.theme" ]; then
          for candidate in \
            /run/current-system/sw/share/icons/hicolor/index.theme \
            "$HOME/.nix-profile/share/icons/hicolor/index.theme"; do
            if [ -f "$candidate" ]; then
              ln -sf "$candidate" "$icon_dir/index.theme"
              break
            fi
          done
        fi

        if command -v update-desktop-database >/dev/null 2>&1; then
          update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
        fi

        if command -v gtk-update-icon-cache >/dev/null 2>&1; then
          gtk-update-icon-cache -f -t "$icon_dir" >/dev/null 2>&1 || true
        fi
      '';
    })
  ];
}
