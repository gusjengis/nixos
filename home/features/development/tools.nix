{
  config,
  pkgs,
  lib,
  ...
}:

let
  # These have no aarch64 build.
  x86Only = pkgs.stdenv.hostPlatform.isx86_64;
in
{
  home.packages =
    with pkgs;
    [
      openssl
    ]
    ++ lib.optionals config.dev.enable [
      cloc
    ]
    ++ lib.optionals config.desktopEnv.enable [
      wtype
      xdotool
      gource
    ]
    ++ lib.optionals (x86Only && config.desktopEnv.enable) [
      lmstudio
    ]
    ++ lib.optionals (config.dev.enable && config.desktopEnv.enable) [
      oxker
      posting
      android-tools
      zulu17
    ]
    ++ lib.optionals (x86Only && config.dev.enable && config.desktopEnv.enable) [
      arduino
      android-studio
    ];
}
