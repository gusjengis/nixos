{
  config,
  pkgs,
  lib,
  ...
}:

{
  home.packages =
    # Wine's 64-bit Wayland build is x86-only.
    lib.optionals (pkgs.stdenv.hostPlatform.isx86_64 && config.personalDesktop.enable) [
      pkgs.wineWow64Packages.waylandFull
    ]
    ++ lib.optionals (config.desktopEnv.enable && config.personalDesktop.enable) [ pkgs.ventoy ]
    ++ lib.optionals config.desktopEnv.enable [
      pkgs.usbutils
    ]
    ++ lib.optionals config.laptop.enable [ pkgs.acpi ];
}
