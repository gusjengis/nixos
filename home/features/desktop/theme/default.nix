# GTK/Qt theming.
#
# Deliberately NOT gated on desktopEnv.enable, unlike every other feature under
# desktop/. The headless machines still run GUI programs such as Thunar, which
# are displayed on another machine over Waypipe, and those programs need the
# icon theme and the GTK/Qt environment hints to render correctly. Gating this
# would leave remote windows unthemed.
{
  config,
  lib,
  pkgs,
  ...
}:

let
  gtkThemeName = "Adwaita-dark";
  iconThemeName = "Papirus-Dark";
  kvantumTheme = "KvAdaptaDark";
in
{
  home.packages = [ pkgs.papirus-icon-theme ];

  ###### Environment hints (kept minimal but practical)
  home.sessionVariables = {
    # Prefer NOT to force GTK_THEME globally, but if you want “no excuses”:
    GTK_THEME = gtkThemeName;

    # Qt
    QT_STYLE_OVERRIDE = "kvantum";
    QT_QPA_PLATFORMTHEME = "qt6ct"; # if you only have qt5ct, change to "qt5ct"

    # Helps some Electron/Chromium builds pick the right defaults
    XDG_CURRENT_DESKTOP = "Hyprland";
    XDG_SESSION_TYPE = "wayland";
  };

  ###### GTK theming + prefer-dark
  gtk = {
    enable = true;

    theme = {
      name = gtkThemeName;
      # For Adwaita(-dark), gnome-themes-extra is fine; you can also omit package.
      package = pkgs.gnome-themes-extra;
    };

    iconTheme = {
      name = iconThemeName;
      package = pkgs.papirus-icon-theme;
    };

    gtk3.extraConfig = {
      "gtk-application-prefer-dark-theme" = 1;
    };

    gtk4.extraConfig = {
      "gtk-application-prefer-dark-theme" = 1;
      # Some apps consult this directly
      "gtk-theme-name" = gtkThemeName;
    };

    gtk4.theme = config.gtk.theme;
  };

  ###### dconf keys that portals + apps actually query
  dconf = {
    enable = true;
    settings = {
      "org/gnome/desktop/interface" = {
        color-scheme = "prefer-dark";
        gtk-theme = gtkThemeName;
        icon-theme = iconThemeName;
      };

      # Optional: if you want dark-ish file chooser / dialogs in some GNOME-ish apps
      "org/gnome/desktop/wm/preferences" = {
        theme = gtkThemeName;
      };
    };
  };

  ###### Kvantum config (Qt dark)
  xdg.configFile."Kvantum/kvantum.kvconfig".text = ''
    [General]
    theme=${kvantumTheme}
  '';

  # Optional: some Qt apps read these
  xdg.configFile."qt5ct/qt5ct.conf".text = ''
    [Appearance]
    style=kvantum
  '';

  xdg.configFile."qt6ct/qt6ct.conf".text = ''
    [Appearance]
    style=kvantum
  '';
}
