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
    # The compositor's own file log (in $XDG_RUNTIME_DIR/hypr/<instance>) is
    # written through an unflushed std::ofstream, so an abrupt death loses the
    # last several KB -- exactly the part that says why it died. Its stdout is
    # fflush'd per line instead, so stdout is captured here, together with
    # start-hyprland's own watchdog messages, which otherwise only ever reach
    # tty1 and scroll away. Requires debug.enable_stdout_logs in hyprland.lua.
    #
    # Redirected rather than tee'd on purpose: tee would re-buffer the stream
    # through its own FILE* and reintroduce the lost tail. The cost is that a
    # failed start prints nothing to tty1; read the log from another VT or
    # over ssh instead. The previous boot is kept as .1.
    initExtra = lib.optionalString config.desktopEnv.enable ''
      if [ -z "$WAYLAND_DISPLAY" ] && [ "x$XDG_VTNR" = "x1" ]; then
        export HYPRLAND_NO_RT=1
        if command -v start-hyprland >/dev/null 2>&1; then
          hyprLogDir="''${XDG_STATE_HOME:-$HOME/.local/state}/hyprland"
          hyprLog="$hyprLogDir/start-hyprland.log"
          if mkdir -p "$hyprLogDir" 2>/dev/null; then
            [ -f "$hyprLog" ] && mv -f "$hyprLog" "$hyprLog.1"
            printf '=== start-hyprland %s ===\n' "$(date -Is)" >> "$hyprLog"
            exec start-hyprland >> "$hyprLog" 2>&1
          fi
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
