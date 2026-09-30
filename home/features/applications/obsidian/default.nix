{
  config,
  pkgs,
  lib,
  repoRoot,
  ...
}:

let
  featureDir = "${repoRoot}/home/features/applications/obsidian";
  vault = "${config.home.homeDirectory}/Documents/Obsidian/Notes";

  # Called by the Quickshell capture popup (CTRL + dictation key) with the
  # transcript; writes it as a new note in Raw/.
  captureNote = pkgs.writeShellApplication {
    name = "capture-note";
    runtimeInputs = [ pkgs.coreutils ];
    text = ''
      exec bash "${featureDir}/capture-note.sh" "$@"
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
  };
}
