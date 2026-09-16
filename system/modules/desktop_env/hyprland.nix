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
    };

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
