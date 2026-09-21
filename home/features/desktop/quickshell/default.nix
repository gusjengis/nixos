{
  config,
  pkgs,
  lib,
  inputs,
  repoRoot,
  ...
}:
let
  # hyprctl has to come from the same fork as the running compositor: its
  # `dispatch` takes Lua, which the nixpkgs build does not speak.
  hyprlandPackages = inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system};
  hyprpickerPackage = inputs.hyprpicker.packages.${pkgs.stdenv.hostPlatform.system}.hyprpicker;
  configRoot = "${repoRoot}/home/features/desktop/quickshell/config";
  wallpaperDir = "${repoRoot}/home/features/desktop/wallpaper";
  python = pkgs.python3.withPackages (ps: [ ps.pygobject3 ]);
  sfPro = pkgs.stdenvNoCC.mkDerivation {
    pname = "sf-pro";
    version = "2026-09-11";
    src = pkgs.fetchurl {
      url = "https://devimages-cdn.apple.com/design/resources/download/SF-Pro.dmg";
      hash = "sha256-loqzuLH5LC2K9h6waA9cIiTE541ZuYa/AEUCp/wBKRg=";
    };
    nativeBuildInputs = [
      pkgs.libarchive
      pkgs.p7zip
    ];
    unpackPhase = ''
      runHook preUnpack
      7z x -y "$src"
      bsdtar -xf Payload~
      runHook postUnpack
    '';
    installPhase = ''
      runHook preInstall
      install -Dm644 Library/Fonts/* -t "$out/share/fonts/opentype"
      runHook postInstall
    '';
    meta = {
      description = "Apple SF Pro typeface";
      homepage = "https://developer.apple.com/fonts/";
      license = lib.licenses.unfree;
      platforms = lib.platforms.all;
    };
  };
  # The hot path (catalog/current/set/preview/random/next/restore) is a
  # compiled binary: it runs on every scroll step in the wallpaper picker, and
  # a Python interpreter plus a double directory scan was most of its latency.
  # Palette lookup here is cache-only (reads metadata.json); matugen itself is
  # only ever invoked by wallpaper-generate-palettes, run manually.
  wallpaperctl = pkgs.rustPlatform.buildRustPackage {
    pname = "wallpaperctl";
    version = "0.1.0";
    src = lib.fileset.toSource {
      root = ./../wallpaper;
      fileset = lib.fileset.unions [
        ./../wallpaper/Cargo.toml
        ./../wallpaper/Cargo.lock
        ./../wallpaper/src
      ];
    };
    cargoLock.lockFile = ./../wallpaper/Cargo.lock;
    nativeBuildInputs = [ pkgs.makeWrapper ];
    postFixup = ''
      wrapProgram $out/bin/wallpaperctl \
        --prefix PATH : ${
          lib.makeBinPath [
            hyprlandPackages.hyprland
            pkgs.hyprpaper
          ]
        }
    '';
  };
  # Manual/periodic: backfills matugen palettes into metadata.json so
  # wallpaperctl's cache-only lookup has something to find. Not on the hot
  # path, so it stays Python; wrapped the same way as the other scripts here
  # purely so it's runnable without hand-prefixing PATH with matugen.
  wallpaperGeneratePalettes = pkgs.writeShellApplication {
    name = "wallpaper-generate-palettes";
    runtimeInputs = [
      pkgs.matugen
      pkgs.python3
    ];
    text = ''
      exec python3 "${wallpaperDir}/generate-palettes.py" "$@"
    '';
  };
  # Publishes curation.json and collects whatever the scheduled fetcher pushed.
  # Shared by the picker's Ctrl+D and the hourly timer below, which is why the
  # script itself takes a lock rather than relying on the callers.
  wallpaperSync = pkgs.writeShellApplication {
    name = "wallpaper-sync";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.git
      pkgs.git-lfs
      pkgs.util-linux
    ];
    text = ''
      exec bash "${wallpaperDir}/wallpaper-sync.sh" "$@"
    '';
  };
  # Ctrl+D in the picker. Flips the hidden flag locally, then pushes in the
  # background so the keypress stays instant.
  wallpaperHide = pkgs.writeShellApplication {
    name = "wallpaper-hide";
    runtimeInputs = [
      pkgs.util-linux
      wallpaperSync
      wallpaperctl
    ];
    text = ''
      exec bash "${wallpaperDir}/wallpaper-hide.sh" "$@"
    '';
  };
  # Manual/periodic backfill of ~/Wallpapers from peapix.com. Enumerates both
  # sections by id, keeps only natively-4K images, and deduplicates on sha256
  # plus a perceptual hash. ImageMagick is what computes that perceptual hash,
  # and git-lfs materialises a stored image when a hash collision has to be
  # settled on pixels in a checkout that has none.
  wallpaperFetchPeapix = pkgs.writeShellApplication {
    name = "wallpaper-fetch-peapix";
    runtimeInputs = [
      pkgs.git
      pkgs.git-lfs
      pkgs.imagemagick
      pkgs.python3
    ];
    text = ''
      exec python3 "${wallpaperDir}/fetch-peapix.py" "$@"
    '';
  };
  # Bing runs a different image per market on most days, so a large part of the
  # library only ever had German, Japanese, French or Chinese prose. This adds
  # English alongside the original so the picker's search works on all of it.
  wallpaperTranslate = pkgs.writeShellApplication {
    name = "wallpaper-translate";
    runtimeInputs = [
      pkgs.python3
      pkgs.translate-shell
    ];
    text = ''
      exec python3 "${wallpaperDir}/translate-metadata.py" "$@"
    '';
  };
  aiUsage = pkgs.writeShellApplication {
    name = "quickshell-ai-usage";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      exec python3 "${configRoot}/../usage.py" "$@"
    '';
  };
  aiAccount = pkgs.writeShellApplication {
    name = "quickshell-ai-account";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      exec python3 "${configRoot}/../usage.py" account "$@"
    '';
  };
  universalSearch = pkgs.writeShellApplication {
    name = "quickshell-search";
    runtimeInputs = [
      hyprlandPackages.hyprland
      pkgs.python3
      pkgs.tmux
      pkgs.xdg-utils
    ];
    text = ''
      export QUICKSHELL_SEARCH_CONFIG="${configRoot}/projects.json"
      exec python3 "${configRoot}/../universal-search.py" "$@"
    '';
  };
  systemControls = pkgs.writeShellApplication {
    name = "quickshell-system-controls";
    runtimeInputs = [
      pkgs.networkmanager
      pkgs.bluez
      pkgs.brightnessctl
      pkgs.python3
    ];
    text = ''
      exec python3 "${configRoot}/../system-controls.py" "$@"
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
    xdg.dataFile."quickshell/laptop".text = if config.laptop.enable then "1" else "0";

    # Waypipe starts its remote server before the metadata helper's wrapper runs.
    home.packages = [
      pkgs.quickshell
      sfPro
      remoteApps
      wallpaperctl
      wallpaperGeneratePalettes
      wallpaperFetchPeapix
      wallpaperTranslate
      wallpaperSync
      wallpaperHide
      aiUsage
      aiAccount
      universalSearch
      systemControls
      hyprpickerPackage
      pkgs.mpv
      pkgs.waypipe
      pkgs.xwayland-satellite
    ];

    # Link the directory so Quickshell and future tooling can atomically replace
    # files without breaking repository-backed configuration.
    xdg.configFile."quickshell".source = config.lib.file.mkOutOfStoreSymlink configRoot;

    # ~/Wallpapers is updated by a scheduled GitHub Actions job rather than by
    # hand, so it needs a pull that is not tied to login. repo-sync only runs on
    # first network after boot, which would leave a machine that stays up for
    # days on a stale library.
    systemd.user.services.wallpaper-sync = {
      Unit = {
        Description = "Sync ~/Wallpapers with its git remote";
        After = [ "network-online.target" ];
        Wants = [ "network-online.target" ];
      };
      Service = {
        Type = "oneshot";
        ExecStart = lib.getExe wallpaperSync;
      };
    };

    systemd.user.timers.wallpaper-sync = {
      Unit.Description = "Pull new wallpapers and publish local curation hourly";
      Timer = {
        OnStartupSec = "2m";
        OnUnitActiveSec = "1h";
        # Keeps several machines waking up from suspend together from hitting
        # the remote at the same instant.
        RandomizedDelaySec = "5m";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };
  };
}
