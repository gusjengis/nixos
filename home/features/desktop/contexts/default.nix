{
  config,
  lib,
  pkgs,
  repoRoot,
  inputs,
  ...
}:
let
  featureDir = "${repoRoot}/home/features/desktop/contexts";
  python = pkgs.python3.withPackages (p: [ p.msgpack ]);
  notebookPython = pkgs.python3.withPackages (p: [
    p.msgpack
    p.pyyaml
    p.plyvel
  ]);
  contextNotes = pkgs.writeShellApplication {
    name = "context-notes";
    runtimeInputs = [ notebookPython ];
    text = ''
      exec python3 -B "${featureDir}/context_notes.py" "$@"
    '';
  };
  contextctl = pkgs.writeShellApplication {
    name = "contextctl";
    runtimeInputs = [
      notebookPython
      pkgs.kitty
      pkgs.tmux
      pkgs.obsidian
      pkgs.thunar
      pkgs.glib
      checkpoint
      inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system}.hyprland
    ];
    text = ''
      exec python3 -B "${featureDir}/contextctl.py" "$@"
    '';
  };
  checkpoint = pkgs.writeShellApplication {
    name = "context-checkpoint";
    runtimeInputs = [
      python
      pkgs.tmux
      pkgs.bash
      pkgs.coreutils
      pkgs.gnused
      pkgs.gnugrep
      pkgs.gawk
      pkgs.procps
      pkgs.libnotify
      pkgs.neovim
      pkgs.kitty
      (import ../../agents/opencode/package.nix { inherit pkgs inputs repoRoot; }).launcher
    ]
    ++ lib.optionals config.desktopEnv.enable [
      inputs.hyprland.packages.${pkgs.stdenv.hostPlatform.system}.hyprland
    ];
    text = ''
      exec python3 -B "${featureDir}/persistence.py" "$@"
    '';
  };
  shutdownBarrier = pkgs.writeShellApplication {
    name = "context-shutdown-barrier";
    runtimeInputs = [
      (pkgs.python3.withPackages (p: [ p.dbus-next ]))
      checkpoint
      pkgs.libnotify
    ];
    text = ''
      exec python3 -B "${featureDir}/shutdown_barrier.py"
    '';
  };
in
{
  options.desktopContexts.enable =
    lib.mkEnableOption "persistent desktop contexts and session restoration"
    // {
      default = true;
    };

  config = lib.mkIf config.desktopContexts.enable {
    home.packages = [
      checkpoint
      shutdownBarrier
      contextNotes
    ]
    ++ lib.optionals config.desktopEnv.enable [ contextctl ];
    home.activation.createSessionsDirectory = lib.mkIf config.desktopEnv.enable (
      lib.hm.dag.entryAfter [ "writeBoundary" ] ''
        mkdir -p "$HOME/sessions"
      ''
    );
    systemd.user.services.context-checkpoint = {
      Unit.Description = "Checkpoint context and machine-local terminal recovery";
      Service = {
        Type = "oneshot";
        ExecStart = "${checkpoint}/bin/context-checkpoint save --reason periodic";
        # Bound background heat without killing legitimate larger exports before
        # they can complete. Foreground close/shutdown captures are independent.
        Nice = 10;
        CPUWeight = 20;
        CPUQuota = "25%";
        TimeoutStartSec = "15min";
        UMask = "0077";
      };
    };
    systemd.user.timers.context-checkpoint = {
      Unit.Description = "Terminal checkpoint timer independent of status bar";
      Timer = {
        OnBootSec = "30s";
        OnUnitInactiveSec = "30s";
      };
      Install.WantedBy = [ "timers.target" ];
    };
    systemd.user.services.context-shutdown-barrier = {
      Unit.Description = "Early terminal checkpoint during logind shutdown delay";
      # Graphical hosts start after importing fresh compositor environment.
      Install.WantedBy = lib.optionals (!config.desktopEnv.enable) [ "default.target" ];
      Service = {
        ExecStart = "${shutdownBarrier}/bin/context-shutdown-barrier";
        Restart = "on-failure";
        RestartSec = 2;
        TimeoutStopSec = 95;
        UMask = "0077";
      };
    };
    systemd.user.services.desktop-contexts = lib.mkIf config.desktopEnv.enable {
      Unit.Description = "Persistent desktop context catalog and automatic activation state";
      Service = {
        ExecStart = "${contextctl}/bin/contextctl watch";
        Restart = "on-failure";
        RestartSec = 2;
        UMask = "0077";
      };
      # Started by session-env-sync with this compositor's display environment.
    };
  };
}
