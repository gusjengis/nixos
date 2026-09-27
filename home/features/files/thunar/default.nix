{
  config,
  lib,
  pkgs,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/files/thunar";
  sfPro = pkgs.callPackage ../../../packages/sf-pro.nix { };
  iconThemeName = "Colloid-Dark-Remote";
  # Wayland's GTK3 backend reads org.gnome.desktop.interface/icon-theme from
  # GSettings at XSETTING priority, above gtk-3.0/settings.ini. Thunar's private
  # XDG_CONFIG_HOME has no dconf user DB, so it otherwise gets Adwaita's schema
  # default even though settings.ini says Colloid. Supply only this key in the
  # private dconf DB; other keys still fall through the system dconf profile.
  iconSettings = pkgs.runCommand "thunar-icon-settings" {
    nativeBuildInputs = [ pkgs.dconf ];
  } ''
    mkdir -p keys
    cat > keys/icons <<'EOF'
    [org/gnome/desktop/interface]
    icon-theme='${iconThemeName}'
    EOF
    dconf compile "$out" keys
  '';
  remoteIcons = pkgs.runCommand "colloid-dark-remote-icon-theme" {
    nativeBuildInputs = [ pkgs.gtk3 ];
  } ''
    theme="$out/share/icons/${iconThemeName}"
    mkdir -p "$out/share/icons"
    # A tiny child icon theme made GTK fall through to Papirus for ordinary
    # folders. Copy Colloid's full index and icons before overriding one glyph
    # so Thunar resolves every other icon exactly as it did before.
    cp -r ${pkgs.colloid-icon-theme}/share/icons/Colloid-Dark "$theme"
    chmod -R u+w "$theme"
    substituteInPlace "$theme/index.theme" \
      --replace-fail 'Name=Colloid-Dark' 'Name=Colloid-Dark-Remote'
    icon=${pkgs.colloid-icon-theme}/share/icons/Colloid-Dark/actions/symbolic/am-network-symbolic.svg
    rm "$theme/places/16/folder-remote.svg" "$theme/places/symbolic/folder-remote-symbolic.svg" 2>/dev/null || true
    cp "$icon" "$theme/places/16/folder-remote.svg"
    cp "$icon" "$theme/places/symbolic/folder-remote-symbolic.svg"
    rm -f "$theme/icon-theme.cache"
    gtk-update-icon-cache -f "$theme"
  '';
  launch = pkgs.writeShellApplication {
    name = "thunar-launch";
    text = builtins.replaceStrings
      [ "@THUNAR@" "@CSS@" ]
      [ "${pkgs.thunar}" "${configRoot}/github-dark.css" ]
      (builtins.readFile ./thunar-launch.sh);
  };
  themedThunar = pkgs.symlinkJoin {
    name = "thunar-themed";
    paths = [ pkgs.thunar ];
    postBuild = ''
      rm "$out/bin/thunar" "$out/bin/Thunar"
      ln -s ${launch}/bin/thunar-launch "$out/bin/thunar"
      ln -s thunar "$out/bin/Thunar"
    '';
  };
in
{
  home.packages = [
    themedThunar
    pkgs.adw-gtk3
    pkgs.colloid-icon-theme
    remoteIcons
    sfPro
    pkgs.tumbler
    pkgs.thunar-volman
    pkgs.thunar-archive-plugin
    pkgs.file-roller
    pkgs.gvfs
    pkgs.udiskie
  ];

  # Only this config tree advertises GitHub Dark, Colloid and SF Pro. Global GTK
  # stays on Adwaita-dark/Papirus for Chromium and other apps.
  home.activation.thunarGtkSettings = lib.hm.dag.entryBetween [ "reloadSystemd" ] [ "writeBoundary" ] ''
    privateHome="${config.xdg.stateHome}/thunar-gtk/gtk-3.0"
    run mkdir -p "$privateHome"
    run ${pkgs.coreutils}/bin/install -m 0644 ${pkgs.writeText "thunar-gtk-settings.ini" ''
      [Settings]
      gtk-theme-name=adw-gtk3-dark
      gtk-icon-theme-name=${iconThemeName}
      gtk-font-name=SF Pro 11
      gtk-application-prefer-dark-theme=1
      gtk-decoration-layout=:
    ''} "$privateHome/settings.ini"
    run ${pkgs.coreutils}/bin/install -Dm644 ${iconSettings} "${config.xdg.stateHome}/thunar-gtk/dconf/user"
  '';

  # Thunar's xfconf settings (menubar visibility, sidebar icons, CSD, ...).
  #
  # The *directory* is linked, not the individual thunar.xml. xfconfd saves a
  # channel by writing a temporary file and renaming it over the target, which
  # replaces a symlink at that path with a regular file rather than following
  # it. That had already happened here: the live thunar.xml had drifted to seven
  # properties while the repository copy still held one, and the next activation
  # would have overwritten the live settings with the stale version. Linking the
  # directory keeps the rename inside the repository, which is the pattern
  # AGENTS.md calls for and the one the hypr config already uses.
  xdg.configFile."xfce4/xfconf/xfce-perchannel-xml" = {
    force = true;
    source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/xfconf";
  };

  # Home Manager's `force` cannot replace a real directory with a symlink, so
  # clear one if it is still there. Any channel worth keeping has already been
  # copied into the repository.
  home.activation.thunarXfconfMigrateToSymlink = lib.hm.dag.entryBefore [ "linkGeneration" ] ''
    xfconfTarget="${config.xdg.configHome}/xfce4/xfconf/xfce-perchannel-xml"
    if [[ -e "$xfconfTarget" && ! -L "$xfconfTarget" ]]; then
      run rm -rf "$xfconfTarget"
    fi
  '';

  systemd.user.services.thunar = {
    Unit.Description = "Thunar file manager daemon";

    Service = {
      Type = "dbus";
      ExecStart = "${themedThunar}/bin/Thunar --daemon";
      BusName = "org.xfce.FileManager";
      KillMode = "process";
      Restart = "on-failure";
      RestartSec = 2;
    };
  };
}
