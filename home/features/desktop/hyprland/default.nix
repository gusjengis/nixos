{
  config,
  pkgs,
  lib,
  inputs,
  repoRoot,
  ...
}:

let
  # Hyprland comes from the fork pinned in flake.nix, not from nixpkgs. This
  # replaces building it by hand in ~/Documents/Code/Hyprland on every machine.
  # The portal is taken from the same flake on purpose: its version has to match
  # the compositor or screen sharing and file pickers misbehave.
  hyprlandPackages = inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system};

  homeRoot = "${repoRoot}/home";
  configDir = "${homeRoot}/features/desktop/hyprland/config";
  hostDir = "${homeRoot}/hosts/${config.host.name}";

  # hyprland.lua requires "platform-variables" directly, so that module name has
  # to resolve on every host. The directory is linked whole, so this per-host
  # choice is a symlink inside the repository rather than a separate link under
  # ~/.config/hypr. It is gitignored.
  #
  # The two files differ only in whether Discord and Slack are launched as
  # native packages or as webapps, which follows whether those packages have a
  # build for this platform. See features/applications/communication.
  platformVariables =
    if pkgs.stdenv.hostPlatform.isx86_64 then "variables.pc.lua" else "variables.mac.lua";

  # Display layout is per machine, so it is tracked in hosts/<name> and linked
  # into the config directory under the name hyprland.lua expects. Hosts
  # without one fall back to the auto layout in hyprland.lua.
  hasMonitors = builtins.pathExists ./../../../hosts/${config.host.name}/monitors.lua;
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [
      hyprlandPackages.hyprland
    ]
    ++ (with pkgs; [
      hypridle
      # Started by autostart.lua. It used to come only from the untracked
      # local.nix, so it was missing on every host but the desktop.
      hyprsunset
      libnotify
      hyprpaper
      font-awesome
      nerd-fonts.iosevka
      nerd-fonts.symbols-only
    ])
    # No aarch64 build.
    ++ lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [
      # Neither package has an aarch64 build.
      pkgs.linux-wallpaperengine
      pkgs.vial
    ];

    # Portals are declared here rather than dropped into home.packages so that
    # exactly one hyprland.portal exists and it is the one built from the same
    # commit as the compositor. A portal from a different Hyprland version
    # breaks screen sharing and the file picker.
    #
    # NixOS used to supply this through programs.hyprland, which also pulled in
    # a second, unused Hyprland from nixpkgs. That module has been removed on
    # the system side; see system/modules/desktop_env/hyprland.nix.
    xdg.portal = {
      enable = true;
      # Home Manager sets NIX_XDG_DESKTOP_PORTAL_DIR to its generated portal
      # directory, which does not include system portal definitions. Include
      # GTK here too so the fallback named by hyprland-portals.conf is visible.
      extraPortals = [
        hyprlandPackages.xdg-desktop-portal-hyprland
        pkgs.xdg-desktop-portal-gtk
      ];
      # Ships hyprland-portals.conf, which says which backend answers which
      # interface under Hyprland.
      configPackages = [ hyprlandPackages.hyprland ];
    };

    # The whole directory is linked back into this repository, so new Hypr
    # config files need no Nix change and host-local files (monitors.lua) never
    # reach the store.
    xdg.configFile."hypr" = {
      source = config.lib.file.mkOutOfStoreSymlink configDir;
      force = true;
    };

    # Home Manager's `force` cannot replace a pre-existing *directory* with a
    # symlink (its `ln -Tsf` gives up on non-empty directories). Until the
    # managed symlink exists, clear any real directory left at the target so
    # linkGeneration can install the repo-backed symlink on every host.
    home.activation.hyprMigrateToSymlink = lib.hm.dag.entryBefore [ "linkGeneration" ] ''
      hyprTarget="$HOME/.config/hypr"
      if [[ -e "$hyprTarget" && ! -L "$hyprTarget" ]]; then
        rm -rf "$hyprTarget"
      fi
    '';

    home.activation.hyprlandHostConfig = lib.hm.dag.entryBefore [ "checkLinkTargets" ] (
      ''
        ln -sfn "${platformVariables}" "${configDir}/platform-variables.lua"
      ''
      + (
        if hasMonitors then
          ''
            ln -sfn "${hostDir}/monitors.lua" "${configDir}/monitors.lua"
          ''
        else
          ''
            rm -f "${configDir}/monitors.lua"
          ''
      )
    );
  };
}
