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
    #
    # The check reads the real controlling tty rather than XDG_VTNR. tmux keeps
    # XDG_VTNR=1 in its global environment for the life of the server, and an
    # SSH attach removes WAYLAND_DISPLAY from the session, so new tmux windows
    # used to pass a variables-only check and exec start-hyprland.
    initExtra =
      lib.optionalString config.desktopEnv.enable ''
        if [ -z "$WAYLAND_DISPLAY" ] && [ -z "$TMUX" ] && [ "$(tty)" = /dev/tty1 ]; then
          export HYPRLAND_NO_RT=1
          if command -v finish-boot-splash >/dev/null 2>&1; then
            finish-boot-splash --prepare
          fi
          if command -v start-hyprland >/dev/null 2>&1; then
            exec start-hyprland
          elif command -v Hyprland >/dev/null 2>&1; then
            exec Hyprland
          fi
        fi
      ''
      # tmux copies update-environment variables (WAYLAND_DISPLAY, DISPLAY,
      # SSH_AUTH_SOCK, ...) from whichever client last attached or focused into
      # the session, but shells that already exist never see the change. Pull
      # the session environment before every command so a pane follows the
      # active client: waypipe when driven over `remote`, the local compositor
      # when back at the desk.
      #
      # PS0 is expanded after a command line is read and before it runs, so a
      # prompt drawn before the client switch still gets the new environment.
      # `''${ ...; }` (bash 5.3) runs in the current shell, unlike `$(...)`, so
      # the eval actually changes this shell's variables.
      + ''
        if [ -n "$TMUX" ]; then
          __tmux_env_sync() {
            local env
            env=$(tmux show-environment -s -t "$TMUX_PANE" 2>/dev/null) && eval "$env"
          }
          PS0="''${PS0}\''${ __tmux_env_sync; }"
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
