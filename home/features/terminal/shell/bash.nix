{
  config,
  lib,
  ...
}:
{
  home.sessionPath = [ "${config.home.homeDirectory}/.cargo/bin" ];

  programs.bash = {
    enable = true;
    # Log in on tty1 and the compositor takes over. Hyprland itself is the fork
    # pinned in flake.nix and installed by features/desktop/hyprland, so this no
    # longer points at a hand-built tree in ~/Documents/Code/Hyprland.
    initExtra = lib.optionalString config.desktopEnv.enable ''
      if [ -z "$WAYLAND_DISPLAY" ] && [ "x$XDG_VTNR" = "x1" ]; then
        export HYPRLAND_NO_RT=1
        if command -v start-hyprland >/dev/null 2>&1; then
          exec start-hyprland
        elif command -v Hyprland >/dev/null 2>&1; then
          exec Hyprland
        fi
      fi
    '';
    bashrcExtra = ''
      export PATH="$HOME/.cargo/bin:$PATH"
      export PS1=" \033[1;35m\]\u\[\033[0m\]@\033[1;31m\]\h\[\033[0m\] \033[1;32m\]\w\[\033[0m\] "
    '';
    profileExtra = ''
      export PATH="$HOME/.cargo/bin:$PATH"
      export PS1=" \033[1;35m\]\u\[\033[0m\]@\033[1;31m\]\h\[\033[0m\] \033[1;32m\]\w\[\033[0m\] "
    '';
    shellAliases = {
      venv = ". .venv/bin/activate";
      vim = "nvim";
      clean = "nix-collect-garbage -d && sudo nix-collect-garbage -d && nix store optimise && sudo nix store optimise";
      nd = "nix develop";
      remote = "waypipe --no-gpu --xwls ssh";
    };
  };

  systemd.user.sessionVariables.PATH = "$HOME/.cargo/bin:$PATH";
}
