{
  config,
  lib,
  pkgs,
  ...
}:
let
  CURSOR_PKG = pkgs.apple-cursor;
  CURSOR_THEME = "macOS";
  CURSOR_SIZE = 24;
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.pointerCursor = {
      enable = true;
      gtk.enable = true;
      x11.enable = true;
      name = CURSOR_THEME;
      package = CURSOR_PKG;
      size = CURSOR_SIZE;
    };

    gtk.cursorTheme = {
      name = CURSOR_THEME;
      package = CURSOR_PKG;
      size = CURSOR_SIZE;
    };

    home.sessionVariables = {
      XCURSOR_THEME = CURSOR_THEME;
      XCURSOR_SIZE = "${toString CURSOR_SIZE}";
    };

    home.packages = with pkgs; [ wl-kbptr ];
  };
}
