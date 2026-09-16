{
  config,
  pkgs,
  lib,
  inputs,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/legacy/ambxst";

  phosphorIcons = pkgs.stdenvNoCC.mkDerivation rec {
    pname = "ttf-phosphor-icons";
    version = "2.1.2";

    src = pkgs.fetchzip {
      url = "https://github.com/phosphor-icons/web/archive/refs/tags/v${version}.zip";
      sha256 = "sha256-96ivFjm0cBhqDKNB50klM7D3fevt8X9Zzm82KkJKMtU=";
      stripRoot = true;
    };

    dontBuild = true;
    installPhase = ''
      runHook preInstall
      install -Dm644 src/*/*.ttf -t $out/share/fonts/truetype
      install -Dm644 LICENSE -t $out/share/licenses/${pname}
      runHook postInstall
    '';

    meta = with pkgs.lib; {
      description = "A flexible icon family for interfaces, diagrams, presentations";
      homepage = "https://phosphoricons.com";
      license = licenses.mit;
      platforms = platforms.all;
    };
  };

  ambxstPackage =
    let
      system = pkgs.stdenv.hostPlatform.system;
      quickshellPkg = inputs.ambxst.inputs.quickshell.packages.${system}.default.override {
        xorg.libxcb = pkgs.libxcb;
      };

      baseEnv =
        with pkgs;
        [
          quickshellPkg
          mesa
          libglvnd
          egl-wayland
          wayland
          qt6.qtbase
          qt6.qtsvg
          qt6.qttools
          qt6.qtwayland
          qt6.qtdeclarative
          qt6.qtimageformats
          kdePackages.qtmultimedia
          kdePackages.qtshadertools
          kdePackages.syntax-highlighting
          brightnessctl
          ddcutil
          fontconfig
          glib
          grim
          imagemagick
          jq
          litellm
          libnotify
          matugen
          power-profiles-daemon
          slurp
          sqlite
          upower
          wl-clip-persist
          wl-clipboard
          wlsunset
          wtype
          zbar
          zenity
          inetutils
          adw-gtk3
          mpvpaper
          ffmpeg
          x264
          playerctl
          pipewire
          wireplumber
          kitty
          tmux
          fuzzel
          networkmanagerapplet
          blueman
          pwvucontrol
          gradia
          kdePackages.breeze-icons
          hicolor-icon-theme
          roboto
          roboto-mono
          league-gothic
          terminus_font
          terminus_font_ttf
          dejavu_fonts
          liberation_ttf
          nerd-fonts.iosevka
          nerd-fonts.symbols-only
          noto-fonts
          noto-fonts-color-emoji
          noto-fonts-cjk-sans
          noto-fonts-cjk-serif
          phosphorIcons
          (tesseract.override {
            enableLanguages = [
              "eng"
              "spa"
              "lat"
              "jpn"
              "chi_sim"
              "chi_tra"
              "kor"
            ];
          })
        ]
        ++ lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [ gpu-screen-recorder ];

      envAmbxst = pkgs.buildEnv {
        name = "Ambxst-env";
        paths = baseEnv;
        pathsToLink = [ "/lib/qt-6/qml" ];
      };

      shellSrc = pkgs.stdenv.mkDerivation {
        pname = "ambxst-shell";
        version = lib.removeSuffix "\n" (builtins.readFile "${inputs.ambxst}/version");
        src = lib.cleanSource inputs.ambxst;
        dontBuild = true;
        installPhase = ''
          mkdir -p $out
          cp -r . $out/
        '';
      };

      launcher = pkgs.writeShellScriptBin "ambxst" ''
        export AMBXST_QS="${quickshellPkg}/bin/qs"
        export PATH="${lib.makeBinPath (baseEnv ++ [ pkgs.python3 ])}:$PATH"
        export QML2_IMPORT_PATH="${envAmbxst}/lib/qt-6/qml:$QML2_IMPORT_PATH"
        export QML_IMPORT_PATH="$QML2_IMPORT_PATH"
        exec ${shellSrc}/cli.sh "$@"
      '';
    in
    launcher;
in
{
  config = lib.mkIf config.desktopEnv.enable {
    # Legacy reference shell: installed and manually launchable, never started
    # automatically or imported into the new Quickshell configuration.
    home.packages = [
      ambxstPackage
      phosphorIcons
    ];

    xdg.configFile."ambxst" = {
      source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/config";
      force = true;
    };

    # Older generations created ~/.config/ambxst as a real directory filled
    # with per-file symlinks into the now-deleted config_files tree. Preserve
    # that directory as a backup before replacing it with the repository-backed
    # directory symlink.
    home.activation.ambxstMigrateToSymlink = lib.hm.dag.entryBefore [ "linkGeneration" ] ''
      ambxstTarget="$HOME/.config/ambxst"
      if [[ -d "$ambxstTarget" && ! -L "$ambxstTarget" ]]; then
        mv "$ambxstTarget" "$ambxstTarget.pre-home-manager-$(date +%Y%m%d%H%M%S)"
      fi
    '';

    xdg.dataFile."ambxst/pinnedapps.json".source =
      config.lib.file.mkOutOfStoreSymlink "${configRoot}/pinnedapps.json";
  };
}
