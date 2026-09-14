{
  config,
  pkgs,
  lib,
  ...
}:
let
  configRoot = "${config.home.homeDirectory}/.home-manager/features/desktop/quickshell/config";
  wallpaperController = "${config.home.homeDirectory}/.home-manager/features/desktop/wallpaper/wallpaperctl.py";
  python = pkgs.python3.withPackages (ps: [ ps.pygobject3 ]);
  wallpaperctl = pkgs.writeShellApplication {
    name = "wallpaperctl";
    runtimeInputs = [
      pkgs.awww
      pkgs.matugen
      pkgs.python3
    ];
    text = ''
      exec python3 "${wallpaperController}" "$@"
    '';
  };
  aiUsage = pkgs.writeShellApplication {
    name = "quickshell-ai-usage";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      exec python3 "${configRoot}/../usage.py" "$@"
    '';
  };
  remoteApps = pkgs.stdenvNoCC.mkDerivation {
    pname = "quickshell-remote-apps";
    version = "1";
    dontUnpack = true;
    nativeBuildInputs = [
      pkgs.gobject-introspection
      pkgs.wrapGAppsHook3
    ];
    buildInputs = [
      python
      pkgs.gtk3
      pkgs.glib
      pkgs.adwaita-icon-theme
    ];
    installPhase = ''
      mkdir -p $out/bin
      install -m755 ${./remote-apps.py} $out/bin/quickshell-remote-apps
      substituteInPlace $out/bin/quickshell-remote-apps \
        --replace-fail '#!/usr/bin/env python3' '#!${python}/bin/python3'
    '';
    preFixup = ''
      gappsWrapperArgs+=(--prefix PATH : ${
        lib.makeBinPath [
          pkgs.waypipe
          pkgs.xwayland-satellite
          pkgs.tailscale
          pkgs.openssh
          pkgs.gtk3
          pkgs.xterm
          pkgs.quickshell
        ]
      })
      gappsWrapperArgs+=(--prefix XDG_DATA_DIRS : ${pkgs.adwaita-icon-theme}/share)
    '';
  };
in
{
  config = lib.mkIf config.desktopEnv.enable {
    # Waypipe starts its remote server before the metadata helper's wrapper runs.
    home.packages = [
      pkgs.quickshell
      remoteApps
      wallpaperctl
      aiUsage
      pkgs.waypipe
      pkgs.xwayland-satellite
    ];

    # Link the directory so Quickshell and future tooling can atomically replace
    # files without breaking repository-backed configuration.
    xdg.configFile."quickshell".source = config.lib.file.mkOutOfStoreSymlink configRoot;
  };
}
