{
  config,
  pkgs,
  lib,
  ...
}:

{
  home.packages =
    with pkgs;
    [
    ]
    ++ lib.optionals config.desktopEnv.enable [
      # TODO: belong in a phone sync/connection folder, not generally used for communication
      scrcpy
      kdePackages.kdeconnect-kde
      kdePackages.kpeople

      (
        (mailspring.override {
          commandLineArgs = "--password-store=gnome-libsecret";
        }).overrideAttrs
        (old: {
          postFixup = (old.postFixup or "") + ''
            wrapProgram $out/bin/mailspring \
              --prefix LD_LIBRARY_PATH : ${lib.makeLibraryPath [ libayatana-appindicator ]}
          '';
        })
      )
    ]
    # No aarch64 builds. The Hyprland keybinds fall back to the webapp
    # launchers where these are missing; see the hyprland feature's
    # platform-variables selection.
    ++ lib.optionals (pkgs.stdenv.hostPlatform.isx86_64 && config.desktopEnv.enable) [
      zoom-us
      slack
    ];

  programs.discord = lib.mkIf (pkgs.stdenv.hostPlatform.isx86_64 && config.desktopEnv.enable) {
    enable = true;
    package = pkgs.discord-canary;
    configName = "discordcanary";
    settings.SKIP_HOST_UPDATE = true;
  };

  # KDE Connect needs one-time pairing after first installation.
}
