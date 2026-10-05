{
  config,
  lib,
  pkgs,
  inputs,
  repoRoot,
  ...
}:
let
  configDir = "${repoRoot}/home/features/desktop/vicinae/config";
  extensionsDir = "${repoRoot}/home/features/desktop/vicinae/extensions";
  themeFile = "${repoRoot}/home/features/desktop/vicinae/spotlight.toml";
  vicinaePackage = inputs.vicinae.packages.${pkgs.stdenv.hostPlatform.system}.default.overrideAttrs (old: {
    patches = (old.patches or [ ]) ++ [ ./spotlight-layout.patch ./spotlight-glass.patch ./spotlight-suggestion.patch ];
    postPatch = (old.postPatch or "") + ''
      substituteInPlace src/server/src/ui/qml/launcher/LauncherWindowLayerShell.qml \
        --replace-fail 'searchBarHeight: 52' 'searchBarHeight: 55' \
        --replace-fail 'Screen.height * 0.2' 'Screen.height * 0.366667' \
        --replace-fail 'LayerShell.Window.exclusionZone: 0' 'LayerShell.Window.exclusionZone: -1' \
        --replace-fail 'screen.height - 37' 'screen.height - 30' \
        --replace-fail 'menu bar occupies top 37px' 'menu bar occupies top 30px' \
        --replace-fail 'Window.margins.top: 37' 'Window.margins.top: 30'
    '';
  });
  vicinaeWithGlass = pkgs.writeShellApplication {
    name = "vicinae-with-glass";
    runtimeInputs = [ vicinaePackage inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system}.hyprland pkgs.jq pkgs.coreutils ];
    text = ''
      library="''${XDG_DATA_HOME:-$HOME/.local/share}/hyprglass/libhyprglass.so"
      if ! hyprctl -j hyprglass status 2>/dev/null | jq -e '.schema == 1' >/dev/null 2>&1; then
        if [[ -f "$library" ]]; then
          hyprctl plugin load "$library" >/dev/null 2>&1 || true
        fi
      fi
      for ((attempt = 0; attempt < 30; attempt++)); do
        if hyprctl -j hyprglass status 2>/dev/null | jq -e '.features.layers.active == true' >/dev/null 2>&1; then
          break
        fi
        sleep 0.1
      done
      if hyprctl -j hyprglass status 2>/dev/null | jq -e '.features.layers.active == true' >/dev/null; then
        export VICINAE_MAC_GLASS=1
        if hyprctl -j hyprglass status 2>/dev/null | jq -e '.macPlaceholder == true' >/dev/null; then
          export VICINAE_MAC_PLACEHOLDER=1
        else
          unset VICINAE_MAC_PLACEHOLDER
        fi
      else
        unset VICINAE_MAC_GLASS
        unset VICINAE_MAC_PLACEHOLDER
      fi
      exec vicinae "$@"
    '';
  };
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ vicinaePackage vicinaeWithGlass ];

    programs.chromium.extensions = [ "kcmipingpfbohfjckomimmahknoddnke" ]; # Vicinae Integration
    home.file.".config/chromium/NativeMessagingHosts/com.vicinae.vicinae.json".source =
      "${vicinaePackage}/etc/chromium/native-messaging-hosts/com.vicinae.vicinae.json";

    xdg.configFile."vicinae".source = config.lib.file.mkOutOfStoreSymlink configDir;
    xdg.dataFile."vicinae/extensions".source = config.lib.file.mkOutOfStoreSymlink extensionsDir;
    xdg.dataFile."vicinae/themes/spotlight.toml".source = config.lib.file.mkOutOfStoreSymlink themeFile;

    home.activation.vicinaeMigrateExtensions = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
      target="''${XDG_DATA_HOME:-$HOME/.local/share}/vicinae/extensions"
      if [[ -d "$target" && ! -L "$target" ]]; then
        run cp -an "$target/." "${extensionsDir}/"
        backup="$target.pre-repo"
        n=1
        while [[ -e "$backup" ]]; do
          backup="$target.pre-repo-$n"
          n=$((n + 1))
        done
        run mv "$target" "$backup"
      fi
    '';

    # Home Manager cannot replace an existing non-empty directory with a link.
    # Keep the original intact for users who configured Vicinae before activation.
    home.activation.vicinaeMigrateConfig = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
      target="$HOME/.config/vicinae"
      if [[ -d "$target" && ! -L "$target" ]]; then
        backup="$target.pre-repo"
        n=1
        while [[ -e "$backup" ]]; do
          backup="$target.pre-repo-$n"
          n=$((n + 1))
        done
        run mv "$target" "$backup"
      fi
    '';

    home.activation.vicinaeMigrateChromiumHost = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
      target="$HOME/.config/chromium/NativeMessagingHosts/com.vicinae.vicinae.json"
      if [[ -e "$target" && ! -L "$target" ]]; then
        backup="$target.pre-repo"
        n=1
        while [[ -e "$backup" ]]; do
          backup="$target.pre-repo-$n"
          n=$((n + 1))
        done
        run mv "$target" "$backup"
      fi
    '';
  };
}
