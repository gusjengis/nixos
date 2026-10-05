{
  config,
  lib,
  pkgs,
  ...
}:

# Obsidian note processing. Raw captures arrive in the vault's Raw/ folder from
# every channel (see notes/CAPTURE_PLAN.md); this host keeps its own synced
# copy of the vault and turns each raw note into a cleaned-up one in
# Normalized/. It runs here rather than on a workstation because it must keep
# working while those are off, and the model it needs is already resident in
# this host's Ollama.
#
# Both units are system services running as the user, not user services: this
# headless host has no login session and no lingering, so user units would
# never start.

let
  cfg = config.notesPipeline;
  user = "gusjengis";
  home = "/home/${user}";
  vault = "${home}/Documents/Obsidian/Notes";
  # Read at runtime only, from the secrets checkout; never evaluated by Nix.
  credentials = "${home}/.config/secrets/obsidian";

  obsidianSync = pkgs.writeShellApplication {
    name = "obsidian-sync";
    runtimeInputs = [
      # System units get a bare PATH; the script is run with `bash`.
      pkgs.bash
      pkgs.obsidian-headless
      pkgs.coreutils
      pkgs.gnugrep
      pkgs.gnused
      pkgs.hostname
    ];
    text = ''
      export OBSIDIAN_CREDENTIALS="${credentials}"
      export OBSIDIAN_VAULT="${vault}"
      # The "Notes" vault, by ID (same as the workstations' sync service).
      export OBSIDIAN_REMOTE_VAULT="bcf1cb4f72f6417ec375921cbf767004"
      exec bash ${../../../home/features/applications/obsidian/obsidian-sync.sh} "$@"
    '';
  };

  normalize = pkgs.writeShellApplication {
    name = "note-normalize";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      exec python3 ${./note-normalize.py} \
        --vault ${lib.escapeShellArg vault} \
        --ollama-url http://127.0.0.1:${toString config.ollama.port}/api/chat \
        --model ${lib.escapeShellArg config.ollama.preload} \
        "$@"
    '';
  };
in
{
  options.notesPipeline.enable = lib.mkEnableOption "Obsidian vault sync and raw note normalization";

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.ollama.enable && config.ollama.preload != null;
        message = "notesPipeline normalizes with the resident Ollama model (ollama.preload).";
      }
    ];

    # `note-normalize [--dry-run] [--force] [stem ...]` for manual runs.
    environment.systemPackages = [ normalize ];

    systemd.services.obsidian-sync = {
      description = "Obsidian Sync (headless) for ${vault}";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
      unitConfig = {
        ConditionPathExists = credentials;
        StartLimitIntervalSec = 0;
      };
      serviceConfig = {
        User = user;
        Group = "users";
        ExecStart = lib.getExe obsidianSync;
        Restart = "always";
        # Backs off to 30 min so a bad password does not hammer the login.
        RestartSec = 30;
        RestartSteps = 6;
        RestartMaxDelaySec = 1800;
      };
    };

    systemd.services.note-normalize = {
      description = "Normalize raw Obsidian notes";
      after = [
        "ollama.service"
        "obsidian-sync.service"
      ];
      unitConfig.ConditionPathIsDirectory = "${vault}/Raw";
      serviceConfig = {
        Type = "oneshot";
        User = user;
        Group = "users";
        ExecStart = lib.getExe normalize;
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ReadWritePaths = [ vault ];
      };
    };

    # Any change in Raw/ (sync delivering a capture or an edit) starts a run at
    # once. Images/ is watched too, since sync may deliver a handwritten note
    # before its page images and the script defers the note until they land.
    systemd.paths.note-normalize = {
      wantedBy = [ "multi-user.target" ];
      pathConfig.PathChanged = [
        "${vault}/Raw"
        "${vault}/Raw/Images"
      ];
    };

    # Nothing changes on disk when an edited note's 10 quiet minutes run out,
    # so a watch alone would never pick it up. This timer covers that, and any
    # change missed while sync or the service was down. A run with nothing to
    # do reads the notes and never touches the model.
    systemd.timers.note-normalize = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "2min";
        OnUnitInactiveSec = "5min";
      };
    };
  };
}
