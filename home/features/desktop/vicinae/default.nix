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
  themeFile = "${repoRoot}/home/features/desktop/vicinae/spotlight.toml";
  vicinaePackage = inputs.vicinae.packages.${pkgs.stdenv.hostPlatform.system}.default;
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ vicinaePackage ];

    programs.chromium.extensions = [ "kcmipingpfbohfjckomimmahknoddnke" ]; # Vicinae Integration
    home.file.".config/chromium/NativeMessagingHosts/com.vicinae.vicinae.json".source =
      "${vicinaePackage}/etc/chromium/native-messaging-hosts/com.vicinae.vicinae.json";

    xdg.configFile."vicinae".source = config.lib.file.mkOutOfStoreSymlink configDir;
    xdg.dataFile."vicinae/themes/spotlight.toml".source =
      config.lib.file.mkOutOfStoreSymlink themeFile;

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
