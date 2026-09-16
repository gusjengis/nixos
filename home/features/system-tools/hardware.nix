{
  config,
  pkgs,
  lib,
  ...
}:

{
  home.packages =
    # Wine's 64-bit Wayland build is x86-only.
    lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [ pkgs.wineWow64Packages.waylandFull ]
    ++ lib.optionals config.desktopEnv.enable [
      pkgs.ventoy
      pkgs.usbutils
    ]
    ++ lib.optionals config.laptop.enable [ pkgs.acpi ];
}
