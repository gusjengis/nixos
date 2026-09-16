{
  config,
  pkgs,
  lib,
  repoRoot,
  ...
}:
let
  deployStateDir = "${config.xdg.stateHome}/home-manager";
  # Held for the whole activation, and taken non-blocking by `update-home`.
  # Activation starts the update service, so without this the service would
  # rebuild and re-activate from inside the activation it was started by.
  deployLockFile = "${deployStateDir}/update.lock";
  repoGroups = lib.concatStringsSep "," (
    [ "core" ]
    ++ lib.optional config.dev.enable "dev"
    ++ lib.optional config.desktopEnv.enable "desktop"
  );

  syncRepos = pkgs.writeShellApplication {
    name = "sync-repos";
    runtimeInputs = with pkgs; [
      coreutils
      gh
      git
      gnused
      sudo
    ];
    text = ''
      export REPO_LIST_DIR=${./repos}
      export LOCAL_REPO_LIST=${repoRoot}/home/features/repo-sync/repos/local.list
      export CLONE_REPO_LIB=${./scripts/clone-repo.sh}
      ${builtins.readFile ./scripts/sync-repos.sh}
    '';
  };

  updateHome = pkgs.writeShellApplication {
    name = "update-home";
    runtimeInputs = [
      pkgs.coreutils
      pkgs.git
      pkgs.util-linux
      syncRepos
    ];
    text = ''
      export HM_REPO=${repoRoot}
      export HM_DEPLOY_STATE_DIR=${deployStateDir}
      export SYNC_REPOS_COMMAND=${lib.getExe syncRepos}
      export REBUILD_COMMAND=${config.home.profileDirectory}/bin/rebuild
      export REHOME_COMMAND=${config.home.profileDirectory}/bin/rehome
      ${builtins.readFile ./scripts/update.sh}
    '';
  };

  updateOnReady = pkgs.writeShellApplication {
    name = "update-home-on-ready";
    runtimeInputs = with pkgs; [
      coreutils
      networkmanager
      wget
    ];
    text = ''
      boot_id="$(cat /proc/sys/kernel/random/boot_id)"
      runtime_dir="''${XDG_RUNTIME_DIR:-/run/user/$UID}"
      stamp="$runtime_dir/home-update-$boot_id.done"
      [ -e "$stamp" ] && exit 0

      if command -v hyprctl >/dev/null 2>&1; then
        waited=0
        timeout="''${HM_HYPR_WAIT_TIMEOUT:-180}"
        until hyprctl -j instances >/dev/null 2>&1; do
          [ "$waited" -ge "$timeout" ] && break
          sleep 2
          waited=$((waited + 2))
        done
      fi

      waited=0
      timeout="''${HM_NETWORK_WAIT_TIMEOUT:-300}"
      until nm-online -q --timeout=5 >/dev/null 2>&1 || wget -q --spider --timeout=5 https://github.com; do
        if [ "$waited" -ge "$timeout" ]; then
          echo "network unavailable after $timeout seconds" >&2
          exit 1
        fi
        sleep 10
        waited=$((waited + 10))
      done

      if ${lib.getExe updateHome}; then
        touch "$stamp"
      else
        exit 1
      fi
    '';
  };
in
{
  home.packages = [
    syncRepos
    updateHome
  ];

  home.sessionVariables.SYNC_REPO_GROUPS = repoGroups;

  # Take the deployment lock for the rest of this activation. The file
  # descriptor stays open until activation exits, so `update-home` started by
  # reloadSystemd below sees the lock and skips instead of rebuilding and
  # re-activating underneath us. Non-blocking on purpose: a manual switch
  # during an automatic update must not wait, Home Manager's own profile lock
  # already serialises the two.
  home.activation.homeUpdateLock = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
    mkdir -p ${deployStateDir}
    exec 9>${deployLockFile}
    ${pkgs.util-linux}/bin/flock -n 9 || true
  '';

  programs.bash.shellAliases = {
    sync = "sync-repos";
    update = "update-home";
  };

  systemd.user.services.home-update-on-first-network = {
    Unit = {
      Description = "Sync repositories and rebuild after first network availability";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
      StartLimitIntervalSec = 3600;
      StartLimitBurst = 3;
    };

    Service = {
      # Do not make default.target wait for a rebuild that reloads this manager.
      Type = "exec";
      ExecStart = lib.getExe updateOnReady;
      Environment = [ "SYNC_REPO_GROUPS=${repoGroups}" ];
      Restart = "on-failure";
      RestartSec = 60;
    };

    Install.WantedBy = [ "default.target" ];
  };
}
