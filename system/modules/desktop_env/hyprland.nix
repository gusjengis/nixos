{
  config,
  pkgs,
  lib,
  ...
}:

{
  options = {
    hyprland.enable = lib.mkEnableOption "enables hyprland";
  };

  config = lib.mkIf config.hyprland.enable {
    # Hyprland itself is NOT installed here. It is built from a personal fork
    # pinned in /etc/nixos/flake.nix and installed by Home Manager, so
    # that every machine tracks the same branch without anyone building it by
    # hand. See home/features/desktop/hyprland there.
    #
    # programs.hyprland used to live here. It was removed because it installed
    # a second Hyprland from nixpkgs, and its capability wrapper at
    # /run/wrappers/bin/Hyprland shadowed the fork on PATH, so start-hyprland
    # launched the nixpkgs build instead. Nothing needed the system copy: no
    # display manager is configured, so its wayland session entry was unused.
    #
    # What that module also provided, and where it now comes from:
    #   - xdg-desktop-portal-hyprland  -> Home Manager, matched to the fork
    #   - xwayland                     -> programs.xwayland below
    #   - the cap_sys_nice wrapper     -> gone; Hyprland runs without elevated
    #     scheduling, which is already how the hand-built binary ran.
    # Preserve the generic Wayland-session integration that
    # programs.hyprland imported alongside the package.
    programs = {
      dconf.enable = lib.mkDefault true;
      xwayland.enable = lib.mkDefault true;
    };

    services = {
      graphical-desktop.enable = true;
      xserver.desktopManager.runXdgAutostartIfNone = lib.mkDefault true;

      # Location for the wallpaper cycle, which follows the sun (see
      # home/features/desktop/wallpaper/src/sun.rs). The user-level
      # wallpaper-locate service asks through geoclue's where-am-i demo, which
      # identifies itself as "geoclue-where-am-i"; whitelisting that id lets it
      # through without an interactive agent. On wpa_supplicant machines
      # geoclue scans Wi-Fi; on iwd ones it can only offer an IP-based fix,
      # which is still plenty for sun angles.
      geoclue2 = {
        enable = true;
        appConfig."geoclue-where-am-i" = {
          isAllowed = true;
          isSystem = false;
        };
      };
    };

    # geoclue 2.8 moved IP geolocation into its own [ip] source, which is off
    # unless a method is named, and the NixOS module does not write that
    # section yet. Without it an iwd machine gets no fix at all, since the
    # Wi-Fi source only scans through wpa_supplicant. `lines` concatenates, so
    # this appends to the module's generated file. ichnaea reuses the Wi-Fi
    # source's BeaconDB URL.
    environment.etc."geoclue/geoclue.conf".text = lib.mkAfter ''

      [ip]
      enable=true
      method=ichnaea
    '';

    security = {
      polkit.enable = true;
      pam.services.swaylock = { };
    };

    services.gnome.gnome-keyring.enable = true;

    security.pam.services = {
      login.enableGnomeKeyring = true;
      gdm.enableGnomeKeyring = true; # or sddm, etc.
    };

    environment.systemPackages = with pkgs; [
      kitty
      wayland
      vulkan-loader
      egl-wayland
      libgbm
      libglvnd
      wayland-protocols
      libxkbcommon
      libGL
      skia
    ];

    # The GTK backend and a default stay system-wide, because Flatpak and any
    # non-Hyprland session rely on them. The Hyprland backend deliberately does
    # NOT live here: it has to match the compositor's commit, so Home Manager
    # installs it from the same flake input and drops a hyprland-portals.conf
    # into ~/.config, which takes precedence over this in a Hyprland session.
    xdg.portal = {
      enable = true;
      extraPortals = [ pkgs.xdg-desktop-portal-gtk ];
      config.common.default = [ "gtk" ];
    };
    environment.sessionVariables.XDG_RUNTIME_DIR = "/run/user/$UID";
    services.flatpak.enable = true;

    fonts.packages = with pkgs; [
      carlito
      commit-mono
      nerd-fonts.meslo-lg
    ];
  };
}
