{
  config,
  lib,
  pkgs,
  ...
}:

# Obsidian note processing. Raw captures arrive in the vault's Raw/ folder from
# every channel (see notes/CAPTURE_PLAN.md); this host keeps its own synced
# copy of the vault, turns each raw note into a cleaned-up one in
# Normalized/, and splits those into linked atomic notes in Thoughts/ and
# Entities/. It runs here rather than on a workstation because it must keep
# working while those are off, and the models it needs are already resident in
# this host's Ollama.
#
# All units are system services running as the user, not user services: this
# headless host has no login session and no lingering, so user units would
# never start.

let
  cfg = config.notesPipeline;
  user = "gusjengis";
  home = "/home/${user}";
  vault = "${home}/Documents/Obsidian/Notes";
  # Read at runtime only, from the secrets checkout; never evaluated by Nix.
  credentials = "${home}/.config/secrets/logins/obsidian";

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

  # Second stage: Normalized/ -> Thoughts/ + Entities/ (notes/EXTRACTION_PLAN.md,
  # notes/DATA_MODEL.md). Its SQLite cache (embeddings, keyword index, merge
  # log) is disposable and lives in the unit's state directory.
  stateDir = "/var/lib/note-extract";
  matchingModel = "jina-v5-matching";
  retrievalModel = "jina-v5-retrieval";
  extractArgs = ''
    --vault ${lib.escapeShellArg vault} \
    --state ${stateDir} \
    --ollama http://127.0.0.1:${toString config.ollama.port} \
    --model ${lib.escapeShellArg config.ollama.preload} \
    --matching-model ${matchingModel} \
    --retrieval-model ${retrievalModel} \
  '';
  python = pkgs.python3.withPackages (ps: [ ps.pyyaml ]);

  extract = pkgs.writeShellApplication {
    name = "note-extract";
    runtimeInputs = [ python ];
    text = ''
      exec python3 ${./note-extract.py} ${extractArgs} --views ${./Thoughts.base} "$@"
    '';
  };

  # Hybrid keyword + semantic search over the vault, from the same indexes.
  search = pkgs.writeShellApplication {
    name = "note-search";
    runtimeInputs = [ python ];
    text = ''
      exec python3 ${./note-extract.py} ${extractArgs} --search "$@"
    '';
  };

  # Third stage: rank open thoughts with Jev (TypeSafe, cloud) against the
  # vault's Facets.md. Its answer cache is disposable; deleting it only costs
  # one full re-score (cents).
  scoreStateDir = "/var/lib/note-score";
  typesafeKey = "${home}/.config/secrets/api_keys/typesafe";
  score = pkgs.writeShellApplication {
    name = "note-score";
    runtimeInputs = [ python ];
    text = ''
      exec python3 ${./note-score.py} \
        --vault ${lib.escapeShellArg vault} \
        --state ${scoreStateDir} \
        --lock ${stateDir}/lock \
        --extract-module ${./note-extract.py} \
        --key-file ${lib.escapeShellArg typesafeKey} \
        "$@"
    '';
  };
in
{
  options.notesPipeline.enable = lib.mkEnableOption "Obsidian vault sync, raw note normalization and thought extraction";

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.ollama.enable && config.ollama.preload != null;
        message = "notesPipeline normalizes with the resident Ollama model (ollama.preload).";
      }
      {
        assertion =
          config.ollama.embedders ? ${matchingModel} && config.ollama.embedders ? ${retrievalModel};
        message = "notesPipeline extraction needs the ${matchingModel} and ${retrievalModel} embedders.";
      }
    ];

    # `note-normalize [--dry-run] [--force] [stem ...]`,
    # `note-extract [--dry-run] [--force] [--no-link] [stem ...]` for manual
    # runs, `note-search QUERY`, and `note-score [--dry-run] [title ...]` /
    # `note-score --show [-v]` for the current ranking.
    environment.systemPackages = [
      normalize
      extract
      search
      score
    ];

    # The state directory is created by the unit; this makes it exist (and
    # belong to the user) for manual runs and searches before the first one.
    systemd.tmpfiles.rules = [
      "d ${stateDir} 0755 ${user} users -"
      "d ${scoreStateDir} 0755 ${user} users -"
    ];

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

    systemd.services.note-extract = {
      description = "Extract thoughts from normalized Obsidian notes";
      after = [
        "ollama.service"
        "ollama-embedders.service"
        "obsidian-sync.service"
        "note-normalize.service"
      ];
      unitConfig.ConditionPathIsDirectory = "${vault}/Normalized";
      serviceConfig = {
        Type = "oneshot";
        User = user;
        Group = "users";
        ExecStart = lib.getExe extract;
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ReadWritePaths = [
          vault
          stateDir
        ];
      };
    };

    # Normalized/ is written only by the normalizer, one atomic file per note,
    # so a change there is always a finished note. Thoughts/ and Entities/ are
    # not watched: the extractor writes them itself.
    systemd.paths.note-extract = {
      wantedBy = [ "multi-user.target" ];
      pathConfig.PathChanged = [ "${vault}/Normalized" ];
    };

    # Retries notes that failed, and picks up anything missed while the
    # service or sync was down. A run with nothing to do never calls the chat
    # model; it only re-embeds thoughts that were edited by hand.
    systemd.timers.note-extract = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "5min";
        OnUnitInactiveSec = "15min";
      };
    };

    systemd.services.note-score = {
      description = "Rank thoughts and sort them into contexts with Jev";
      after = [
        "network-online.target"
        "obsidian-sync.service"
        "note-extract.service"
      ];
      wants = [ "network-online.target" ];
      unitConfig = {
        ConditionPathExists = [
          typesafeKey
          "${vault}/Facets.md"
        ];
      };
      serviceConfig = {
        Type = "oneshot";
        User = user;
        Group = "users";
        ExecStart = lib.getExe score;
        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ReadWritePaths = [
          vault
          stateDir
          scoreStateDir
        ];
      };
    };

    # Every finished extraction re-ranks (new thoughts and new links change
    # neighbors), as does an edit to Facets.md or a context note. Answers are
    # cached per question, so a run only asks what changed.
    systemd.services.note-extract.unitConfig.OnSuccess = [ "note-score.service" ];
    systemd.paths.note-score = {
      wantedBy = [ "multi-user.target" ];
      pathConfig.PathChanged = [
        "${vault}/Facets.md"
        "${vault}/Contexts"
      ];
    };

    # Nightly catch-all: status edits made by hand, runs whose API calls
    # failed, and anything missed while the network was down.
    systemd.timers.note-score = {
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "*-*-* 03:30";
        Persistent = true;
      };
    };
  };
}
