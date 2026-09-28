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
    ++ lib.optionals (config.dev.enable && config.desktopEnv.enable) [
      oxker
      posting
      android-tools
      zulu17
    ];
}
