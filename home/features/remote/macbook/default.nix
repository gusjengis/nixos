{ config, lib, pkgs, repoRoot, ... }:
let
  python = pkgs.python3.withPackages (ps: [ ps.pygobject3 ps.pycairo ps.tomli-w ]);
  launcher = pkgs.writeShellApplication {
    name = "macbook-remote";
    runtimeInputs = [ pkgs.openssh pkgs.libnotify pkgs.rustdesk-flutter ];
    text = ''
      export GI_TYPELIB_PATH=${lib.makeSearchPathOutput "out" "lib/girepository-1.0" [
        pkgs.gtk-vnc pkgs.gtk3 pkgs.glib pkgs.gdk-pixbuf pkgs.pango pkgs.atk pkgs.harfbuzz
        pkgs.gobject-introspection
      ]}
      exec ${python}/bin/python ${config.xdg.configHome}/macbook-remote/rustdesk.py "$@"
    '';
  };
in {
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ launcher ];
    xdg.configFile."macbook-remote".source = config.lib.file.mkOutOfStoreSymlink
      "${repoRoot}/home/features/remote/macbook";
    xdg.desktopEntries.macbook = {
      name = "MacBook";
      genericName = "Mac remote desktop";
      comment = "Control the MacBook with automatic window-sized resolution";
      exec = lib.getExe launcher;
      icon = "${config.xdg.configHome}/macbook-remote/apple.svg";
      terminal = false;
      categories = [ "Network" "RemoteAccess" ];
      settings.Keywords = "Mac;macOS;RustDesk;remote;desktop;";
    };
  };
}
