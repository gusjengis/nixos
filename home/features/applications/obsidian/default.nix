{
  config,
  pkgs,
  lib,
  repoRoot,
  hostName,
  ...
}:

let
  featureDir = "${repoRoot}/home/features/applications/obsidian";
  vault = "${config.home.homeDirectory}/Documents/Obsidian/Notes";

  # Templater's template parser (the exact WASM bundled in the Templater
  # plugin, 2.x) and moment, which Obsidian exposes to templates. Pinned
  # npm tarballs: raw-note.mjs needs nothing else.
  rawNoteLib = pkgs.runCommand "raw-note-lib" { } ''
    mkdir -p $out/rusty_engine $out/moment
    tar xzf ${
      pkgs.fetchurl {
        url = "https://registry.npmjs.org/@silentvoid13/rusty_engine/-/rusty_engine-0.4.0.tgz";
        hash = "sha256-LKiVu9uj2KoCmzZM65AhQ/oEnSMQkQfRAyNb51jpM9U=";
      }
    } -C $out/rusty_engine --strip-components=1
    tar xzf ${
      pkgs.fetchurl {
        url = "https://registry.npmjs.org/moment/-/moment-2.30.1.tgz";
        hash = "sha256-UiGan+5eH6reTHJTbBc8VM7dXiYZJy3QwlGjCur83ow=";
      }
    } -C $out/moment --strip-components=1
    # The package ships ES module syntax without declaring it.
    echo '{"type": "module"}' > $out/rusty_engine/package.json
  '';

  # Creates a raw note by executing the vault's "Templates/Raw Note.md"
  # headless (see raw-note.mjs); the template is the only definition of the
  # format. Called by the Quickshell capture popup (CTRL + dictation key) and
  # the Supernote import. Source defaults to desktop-dictation; override with
  # --source or CAPTURE_SOURCE.
  captureNote = pkgs.writeShellApplication {
    name = "capture-note";
    runtimeInputs = [ pkgs.nodejs ];
    text = ''
      export OBSIDIAN_VAULT="''${OBSIDIAN_VAULT:-${vault}}"
      export RAW_NOTE_LIB="${rawNoteLib}"
      exec node "${featureDir}/raw-note.mjs" "$@"
    '';
  };

  # Explicit deletion of a raw note and everything generated from it (see
  # note-delete.py); the pipeline itself never deletes notes.
  noteDelete = pkgs.writeShellApplication {
    name = "note-delete";
    runtimeInputs = [ pkgs.python3 ];
    text = ''
      exec python3 "${featureDir}/note-delete.py" --vault "''${OBSIDIAN_VAULT:-${vault}}" "$@"
    '';
  };

  # Read at runtime only: Nix must never evaluate the secret, or it would be
  # copied into the world-readable store.
  credentials = "${config.home.homeDirectory}/.config/secrets/obsidian";

  obsidianSync = pkgs.writeShellApplication {
    name = "obsidian-sync";
    runtimeInputs = [
      pkgs.obsidian-headless
      pkgs.coreutils
      pkgs.gnugrep
      pkgs.gnused
      pkgs.hostname
    ];
    text = ''
      export OBSIDIAN_CREDENTIALS="${credentials}"
      export OBSIDIAN_VAULT="${vault}"
      # The "Notes" vault, by ID so a rename or a second "Notes" cannot
      # redirect sync.
      export OBSIDIAN_REMOTE_VAULT="bcf1cb4f72f6417ec375921cbf767004"
      exec bash "${featureDir}/obsidian-sync.sh" "$@"
    '';
  };
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [
      pkgs.obsidian
      # `ob`: Obsidian Sync without the desktop app. This machine syncs through
      # the service below instead of the app's Sync core plugin, which must stay
      # disabled here: Obsidian warns that running both on one device conflicts.
      pkgs.obsidian-headless
      captureNote
      noteDelete
    ];

    home.activation.createObsidianVaultDirectory = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
      mkdir -p "${vault}/Raw"
      if [ -f "${credentials}" ]; then
        chmod 600 "${credentials}"
      fi
    '';

    # Keeps the vault synced whether or not Obsidian is open, so captures reach
    # other devices immediately. Login and vault linking happen on first start
    # from the secrets repo (see obsidian-sync.sh); nothing is done by hand.
    systemd.user.services.obsidian-sync = {
      Unit = {
        Description = "Obsidian Sync (headless) for ${vault}";
        After = [ "network-online.target" ];
        Wants = [ "network-online.target" ];
        # Machines without the secrets repo stay inactive instead of failing.
        ConditionPathExists = credentials;
        StartLimitIntervalSec = 0;
      };
      Service = {
        ExecStart = lib.getExe obsidianSync;
        Restart = "always";
        # Backs off to 30 min so a bad password or an offline boot does not
        # hammer Obsidian's login endpoint.
        RestartSec = 30;
        RestartSteps = 6;
        RestartMaxDelaySec = 1800;
      };
      Install.WantedBy = [ "default.target" ];
    };

    systemd.user.services.supernote-capture-import = lib.mkIf (hostName == "pc") {
      Unit = {
        Description = "Import processed Supernote captures into Obsidian";
        ConditionPathIsMountPoint = "/data";
        ConditionPathExists = "/data/Supernote/.capture-backups/outbox";
      };
      Service = {
        Type = "oneshot";
        ExecStart = "${lib.getExe pkgs.python3} ${featureDir}/capture-import.py --outbox /data/Supernote/.capture-backups/outbox --vault ${vault} --capture-note ${lib.getExe captureNote}";
      };
    };

    systemd.user.timers.supernote-capture-import = lib.mkIf (hostName == "pc") {
      Unit.Description = "Import processed Supernote captures periodically";
      Timer = {
        OnBootSec = "2min";
        OnUnitActiveSec = "2min";
        Persistent = true;
      };
      Install.WantedBy = [ "timers.target" ];
    };
  };
}
