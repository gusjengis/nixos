{
  config,
  lib,
  pkgs,
  ...
}:

# Nightly wallpaper collection, formerly GitHub Actions.
#
# This replaces .github/workflows/fetch-wallpapers.yml in the Wallpapers repo,
# which ran the same three scripts on a hosted runner and pushed the result.
# It moved here when the repository moved to omega's Forgejo (forgejo.nix): the
# job has to run wherever it can push tens of gigabytes of git-LFS without a
# bill, and GitHub was charging for exactly that storage.
#
# What the job does, unchanged from the workflow:
#
#   1. fetch-peapix.py --incremental
#        Peapix republishes bing's twelve markets plus spotlight, which between
#        them yield roughly three or four distinct 4K images a day. Walks ids
#        downward from the newest known one, re-checking `margin` ids below it
#        in case a market published late. Deduplicates against the sha256 and
#        perceptual hashes already in metadata.json.
#   2. translate-metadata.py
#        Titles arrive in each market's own language; this fills in English.
#   3. generate-palettes.py
#        Warms the matugen palette cache so the picker does not pay ~0.3s per
#        wallpaper the first time it is scrolled past.
#   4. classify-sun.py --budget
#        Asks the vision model on this host's Ollama which phases of the day
#        (night, twilight, golden, day) each unlabelled image belongs to, so
#        wallpaperctl can follow the sun. New images are still real files at
#        this point; older ones are read straight out of the forge's LFS store
#        by content hash, which is why the service user is in the forgejo
#        group. The budget bounds a run: a full relabel (the first pass, or a
#        prompt change bumping the script's VERSION) clears over a few nights
#        instead of blowing the unit timeout. A labelling failure never blocks
#        publishing new images.
#
# Then it commits and pushes. Three behaviours from the workflow are kept
# deliberately and are not incidental:
#
#   - The checkout holds LFS *pointers*, not images (GIT_LFS_SKIP_SMUDGE). The
#     workflow used `lfs: false` for the same reason: deduplication reads
#     hashes out of metadata.json, so the ~15 GB of pixels are never needed.
#     Only fetch-peapix.py's unresolved-hash-collision path materialises a
#     single image, on demand, and it calls `git lfs pull` itself. Palettes
#     still work because they are only computed for newly downloaded images,
#     which are real files on disk at that point.
#   - curation.json is never staged here. Workstations own it (hidden
#     wallpapers, written by wallpaper-sync.sh) and staging it would make this
#     job and every desktop fight over the same file.
#   - Every new image is verified to have become an LFS pointer before the
#     commit is allowed. If the filter were somehow inactive, multi-megabyte
#     blobs would enter history permanently, and no later commit could undo it.
#
# Differences from the workflow, all intentional:
#
#   - A systemd timer instead of `on.schedule`, and no runner anywhere. One
#     job on one schedule does not need a CI engine to start it.
#   - actions/checkout is gone; a plain clone does the same thing without
#     needing a JavaScript action, and therefore without needing Node on the
#     host at all.
#   - The GITHUB_TOKEN is replaced by a repository-scoped Forgejo deploy key,
#     generated below on first start and registered by forgejo-bootstrap.
#   - The pointer check covers .png as well as .jpg. .gitattributes has always
#     tracked both, but the workflow only ever verified .jpg.
let
  cfg = config.wallpaperFetch;
  forge = config.forge;

  stateDir = "/var/lib/wallpaper-fetch";
  repoDir = "${stateDir}/Wallpapers";
  cacheDir = "${stateDir}/cache";
  sshDir = "${stateDir}/ssh";
  deployKey = "${sshDir}/id_ed25519";
  knownHosts = "${sshDir}/known_hosts";

  # The forge runs as its own user and has to read the key it is asked to
  # authorise, so the public half is published outside the 0700 directory
  # holding the private one instead of loosening that directory.
  publishedKey = "${stateDir}/deploy-key.pub";

  remote = "ssh://git@${forge.domain}:${toString forge.sshPort}/${forge.adminUser}/${cfg.repository}.git";

  fetchWallpapers = pkgs.writeShellApplication {
    name = "wallpaper-fetch";
    runtimeInputs = with pkgs; [
      # git-lfs runs GIT_SSH_COMMAND through an `sh` it looks up on PATH (git
      # itself hardcodes /bin/sh), and systemd's default PATH has none, so
      # without this every LFS upload fails with "executable file not found".
      bash
      coreutils
      git
      git-lfs
      gnugrep
      openssh
      # The pipeline's own tools come from the repository's flake, not from
      # here; this is only what is needed to enter that flake.
      config.nix.package
    ];
    text = ''
      export HOME=${stateDir}
      export GIT_SSH_COMMAND="ssh -i ${deployKey} -o IdentitiesOnly=yes -o UserKnownHostsFile=${knownHosts} -o StrictHostKeyChecking=accept-new"

      # Keep the working tree as pointers. See the header.
      export GIT_LFS_SKIP_SMUDGE=1

      # The scripts address the library through these rather than $HOME, which
      # is what lets the same code run here and on a workstation.
      export WALLPAPER_DIR=${repoDir}
      export WALLPAPER_CACHE_DIR=${cacheDir}
      export MARGIN=${toString cfg.margin}
      export LABEL_BUDGET=${toString cfg.labelBudgetMinutes}
      export OLLAMA_URL=http://127.0.0.1:${toString config.ollama.port}
      export WALLPAPER_LFS_STORE=${config.services.forgejo.lfs.contentDir}

      if [ ! -d ${repoDir}/.git ]; then
        echo "cloning ${cfg.repository} from the forge"
        git clone ${lib.escapeShellArg remote} ${repoDir}
      fi

      cd ${repoDir}

      git remote set-url origin ${lib.escapeShellArg remote}
      git config user.name "wallpaper-fetch"
      git config user.email "wallpaper-fetch@${forge.domain}"

      # Explicit rather than trusting inheritance: without the filter installed
      # locally, images would be committed as raw blobs.
      git lfs install --local

      git fetch --quiet origin ${cfg.branch}

      # This checkout is disposable and this job is its only author, so
      # discarding local state is always the right move. It also self-heals the
      # case where a previous run committed but could not push: metadata.json
      # rewinds with the images, so the fetcher simply collects them again.
      git switch --quiet --force ${cfg.branch}
      git reset --quiet --hard origin/${cfg.branch}
      git clean --quiet -fd

      # The repository's own flake pins ImageMagick 7 (`magick`, absent from
      # v6), matugen and translate-shell, so the pipeline sees the same
      # versions here as on a workstation. $MARGIN is left for the inner shell
      # on purpose: expanding it out here would happen before nix has built
      # the environment.
      # shellcheck disable=SC2016
      nix develop --command bash -euo pipefail -c '
        python3 fetch-peapix.py --incremental --incremental-margin "$MARGIN" --rate 12
        python3 translate-metadata.py --rate 6
        python3 generate-palettes.py
        python3 classify-sun.py --budget "$LABEL_BUDGET" \
          || echo "sun labelling failed; publishing the rest anyway" >&2
      '

      if [ -z "$(git status --porcelain)" ]; then
        echo "no new wallpapers"
        exit 0
      fi

      git add -- . ':!curation.json'
      if git diff --cached --quiet; then
        echo "only curation.json changed, which belongs to the workstations"
        exit 0
      fi

      added=0
      for image in $(git diff --cached --name-only --diff-filter=A -- '*.jpg' '*.png'); do
        # Read the head of the staged blob into a variable rather than piping
        # into `head`: an early-exiting head can SIGPIPE git, and under pipefail
        # that would read as "not a pointer" and abort a perfectly good run.
        staged="$(git cat-file -p ":$image" 2>/dev/null | head -c 64 || true)"
        case "$staged" in
          "version https://git-lfs"*) ;;
          *)
            echo "$image was not converted to an LFS pointer, refusing to commit" >&2
            exit 1
            ;;
        esac
        added=$((added + 1))
      done

      # A run can change only metadata: a labelling instalment, a late
      # translation. Say so instead of announcing zero new wallpapers.
      if [ "$added" -gt 0 ]; then
        git commit --quiet -m "Add $added wallpaper(s) from peapix"
      else
        git commit --quiet -m "Update wallpaper metadata"
      fi

      # A workstation may have pushed a curation change since the fetch above.
      for attempt in 1 2 3; do
        if git push --quiet origin ${cfg.branch}; then
          echo "pushed $added wallpaper(s)"
          exit 0
        fi
        echo "push rejected, rebasing (attempt $attempt)"
        git pull --rebase --autostash origin ${cfg.branch}
      done

      echo "could not push after 3 attempts" >&2
      exit 1
    '';
  };
in
{
  options.wallpaperFetch = {
    enable = lib.mkEnableOption "the nightly peapix wallpaper collection job";

    repository = lib.mkOption {
      type = lib.types.str;
      default = "Wallpapers";
      description = "Forge repository holding the library.";
    };

    branch = lib.mkOption {
      type = lib.types.str;
      default = "main";
      description = "Branch the job publishes to.";
    };

    margin = lib.mkOption {
      type = lib.types.int;
      default = 50;
      description = ''
        How many peapix ids below the newest known one to re-check, covering
        markets that published behind the others. Was the workflow_dispatch
        input of the same name.
      '';
    };

    labelBudgetMinutes = lib.mkOption {
      type = lib.types.int;
      default = 90;
      description = ''
        Minutes classify-sun.py may spend per run. At about 2.3s an image this
        labels roughly 2300, so a full relabel of the library takes two nights.
        Must leave room under the unit timeout for fetching and pushing.
      '';
    };

    schedule = lib.mkOption {
      type = lib.types.str;
      default = "*-*-* 05:40:00 UTC";
      description = ''
        When to run, as a systemd calendar expression. The default is the
        workflow's `40 5 * * *`: comfortably after every bing market has rolled
        over to a new day. Held in UTC for that reason, so it does not drift
        with daylight saving.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.forge.enable;
        message = "wallpaperFetch.enable pushes to the local forge, so forge.enable must be true.";
      }
      {
        assertion = config.ollama.enable;
        message = "wallpaperFetch.enable labels images with the local Ollama, so ollama.enable must be true.";
      }
    ];

    users.groups.wallpaper-fetch = { };
    users.users.wallpaper-fetch = {
      isSystemUser = true;
      group = "wallpaper-fetch";
      home = stateDir;
      createHome = true;
      description = "Owns the wallpaper library checkout and its forge deploy key";
      # Read access to the forge's LFS store, which is the only full copy of
      # the images on this machine: the checkout here holds pointers. Forgejo
      # writes objects 0640 and directories 0750 under its own group, so
      # membership is all the labelling step needs to read them in place.
      extraGroups = [ "forgejo" ];
    };

    systemd.tmpfiles.rules = [
      # 0751: the forge user needs to traverse this to reach deploy-key.pub,
      # but must not be able to list the checkout or the key directory.
      "d ${stateDir} 0751 wallpaper-fetch wallpaper-fetch - -"
      "d ${cacheDir} 0750 wallpaper-fetch wallpaper-fetch - -"
      "d ${sshDir} 0700 wallpaper-fetch wallpaper-fetch - -"
    ];

    # The forge needs the public half to authorise pushes, so this has to come
    # first and is the reason forge.deployKeys takes a path instead of a key:
    # the private half must never reach the Nix store.
    systemd.services.wallpaper-fetch-key = {
      description = "Generate the wallpaper-fetch deploy key";
      before = [ "forgejo-bootstrap.service" ];
      requiredBy = [ "forgejo-bootstrap.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        User = "wallpaper-fetch";
        Group = "wallpaper-fetch";
        UMask = "0077";
      };
      script = ''
        if [ ! -s ${deployKey} ]; then
          ${pkgs.openssh}/bin/ssh-keygen -q -t ed25519 -N "" \
            -C "wallpaper-fetch@${config.networking.hostName}" -f ${deployKey}
        fi

        # Explicit mode rather than the unit's 0077 umask, so the forge can
        # actually read what it is being asked to register.
        install -m 0644 ${deployKey}.pub ${publishedKey}
      '';
    };

    forge.repositories = [ cfg.repository ];
    forge.deployKeys = [
      {
        repository = cfg.repository;
        title = "wallpaper-fetch";
        publicKeyFile = publishedKey;
      }
    ];

    systemd.services.wallpaper-fetch = {
      description = "Collect new peapix wallpapers and publish them to the forge";
      after = [
        "network-online.target"
        "tailscaled.service"
        "forgejo-bootstrap.service"
        "ollama.service"
      ];
      wants = [
        "network-online.target"
        "forgejo-bootstrap.service"
      ];
      serviceConfig = {
        Type = "oneshot";
        User = "wallpaper-fetch";
        Group = "wallpaper-fetch";
        WorkingDirectory = stateDir;
        ExecStart = lib.getExe fetchWallpapers;

        # A normal run takes minutes. The ceiling covers the labelling budget
        # plus a slow fetch, and the first run downloading the flake closure.
        TimeoutStartSec = "3h";

        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ReadWritePaths = [
          stateDir
          # `nix develop` builds through the daemon, and connecting to a unix
          # socket counts as writing to it. Under ProtectSystem=strict the whole
          # hierarchy is read-only, so without this the socket connect fails
          # with EROFS. The same path covers the temproots the client writes to
          # keep its build from being collected mid-run.
          "/nix/var/nix"
        ];
      };
    };

    systemd.timers.wallpaper-fetch = {
      description = "Nightly peapix wallpaper collection";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = cfg.schedule;
        # Catch up after downtime: omega being off overnight should not cost a
        # day of wallpapers.
        Persistent = true;
        RandomizedDelaySec = "10m";
      };
    };
  };
}
