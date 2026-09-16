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
        if command -v start-hyprland >/dev/null 2>&1; then
          exec start-hyprland
        elif command -v Hyprland >/dev/null 2>&1; then
          exec Hyprland
        fi
      fi
    '';
    bashrcExtra = ''
      export PATH="$HOME/.cargo/bin:$PATH"
      TS_NAME=""
      if command -v tailscale >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
        TS_NAME="$(tailscale status --json 2>/dev/null | jq -r '.Self.DNSName')"
        if [ -n "$TS_NAME" ] && [ "$TS_NAME" != "null" ]; then
          TS_NAME="$(printf '%s' "$TS_NAME" | cut -d. -f1)"
        else
          TS_NAME=""
        fi
      fi

      if [ -n "$TS_NAME" ]; then
        export PS1=" \033[1;35m\]\u\[\033[0m\]@\033[1;31m\]''${TS_NAME}\[\033[0m\] \033[1;32m\]\w\[\033[0m\] "
      else
        export PS1=" \033[1;35m\]\u\[\033[0m\] \033[1;32m\]\w\[\033[0m\] "
      fi
    '';
    profileExtra = ''
      export PATH="$HOME/.cargo/bin:$PATH"
      TS_NAME=""
      if command -v tailscale >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
        TS_NAME="$(tailscale status --json 2>/dev/null | jq -r '.Self.DNSName')"
        if [ -n "$TS_NAME" ] && [ "$TS_NAME" != "null" ]; then
          TS_NAME="$(printf '%s' "$TS_NAME" | cut -d. -f1)"
        else
          TS_NAME=""
        fi
      fi

      if [ -n "$TS_NAME" ]; then
        export PS1=" \033[1;35m\]\u\[\033[0m\]@\033[1;31m\]''${TS_NAME}\[\033[0m\] \033[1;32m\]\w\[\033[0m\] "
      else
        export PS1=" \033[1;35m\]\u\[\033[0m\] \033[1;32m\]\w\[\033[0m\] "
      fi
    '';
    shellAliases = {
      venv = ". .venv/bin/activate";
      vim = "nvim";
      clean = "nix-collect-garbage -d && sudo nix-collect-garbage -d && nix store optimise && sudo nix store optimise";
      nd = "nix develop --impure";
      remote = "waypipe --no-gpu --xwls ssh";
    };
  };

  systemd.user.sessionVariables.PATH = "$HOME/.cargo/bin:$PATH";
}
