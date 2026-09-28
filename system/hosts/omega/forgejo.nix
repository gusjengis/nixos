{
  config,
  lib,
  pkgs,
  ...
}:

# Forgejo, omega's private git forge on the tailnet.
#
# Exists because GitHub bills git-LFS storage past 1 GB and the wallpaper
# library is tens of gigabytes of it, growing daily. Self-hosting removes the
# meter entirely; see wallpaper_fetch.nix for the job that feeds it.
#
# - Web UI at http://omega.tail29bd65.ts.net:3000, tailnet only.
# - Git over SSH on port 2222, tailnet only. The fleet's own key authenticates,
#   so a new machine needs no forge-specific setup beyond the secrets repo.
# - Plain HTTP on purpose: WireGuard already encrypts every tailnet hop, and a
#   TLS terminator here would only add a certificate to babysit. Nothing is
#   exposed with `tailscale funnel`, unlike alpha's services.
# - State lives on omega's local NVMe rather than alpha's mirror. Everything
#   here is reproducible (images re-download from peapix, metadata regenerates
#   from the scripts), so paying NFS latency for redundancy is not worth it.
#   That choice is also why nothing below is backed up.
#
# Actions are deliberately off. Only one automated job exists and it is a plain
# systemd timer next door, so a runner would be a second moving part with
# nothing to run. Set `forge.actions.enable` if a repo ever needs real CI.
let
  cfg = config.forge;

  stateDir = "/var/lib/forgejo";
  adminPasswordFile = "${stateDir}/admin-password";

  # Scoped to exactly what bootstrapForge below does: register keys and create
  # repositories. Kept out of the store because it is a live credential.
  apiTokenFile = "${stateDir}/bootstrap-token";

  # The public half of the key every workstation already offers (`Host *` in
  # home/features/ssh/config points at ~/.config/secrets/ssh/fleet_ed25519).
  # Registering it here is what makes `git push` work fleet-wide with no
  # per-machine step.
  fleetKeyPath = ./../../keys/fleet_ed25519.pub;

  forgejoExe = lib.getExe config.services.forgejo.package;
  localApi = "http://127.0.0.1:${toString cfg.httpPort}/api/v1";

  # Written as a script rather than inline so the quoting stays readable and
  # shellcheck runs over it at build time.
  bootstrapForge = pkgs.writeShellApplication {
    name = "forgejo-bootstrap";
    runtimeInputs = with pkgs; [
      coreutils
      curl
      gawk
      gnugrep
      jq
    ];
    text = ''
      api_token=""

      api() {
        # --fail-with-body so a 4xx still prints Forgejo's error message
        # instead of an empty body and a bare exit code.
        curl --silent --show-error --fail-with-body \
          --header "Authorization: token $api_token" \
          --header "Content-Type: application/json" "$@"
      }

      # The CLI talks to the database directly, but `forgejo migrate` runs in
      # forgejo.service's preStart, so waiting for HTTP is also how we wait for
      # the schema to exist.
      ready=""
      for _ in $(seq 1 60); do
        if curl --silent --fail --output /dev/null \
            http://127.0.0.1:${toString cfg.httpPort}/api/healthz; then
          ready=1
          break
        fi
        sleep 2
      done
      if [ -z "$ready" ]; then
        echo "forgejo did not answer /api/healthz within 120s" >&2
        exit 1
      fi

      # Column 2 of `admin user list` is the username. Collected into a variable
      # first: `list | awk | grep -q` would let grep exit early, and under
      # pipefail a SIGPIPE'd awk reads as "user absent", which would then try to
      # recreate an existing account and fail the unit on every boot.
      existing_users="$(
        ${forgejoExe} admin user list 2>/dev/null | awk 'NR > 1 { print $2 }' || true
      )"

      if ! grep -qxF ${lib.escapeShellArg cfg.adminUser} <<< "$existing_users"; then
        echo "creating administrator ${cfg.adminUser}"
        ${forgejoExe} admin user create \
          --username ${lib.escapeShellArg cfg.adminUser} \
          --password "$(cat ${adminPasswordFile})" \
          --email ${lib.escapeShellArg cfg.adminEmail} \
          --admin --must-change-password=false
      fi

      # Token names are unique per user and cannot be deleted from the CLI, so
      # a fresh name each time keeps this re-runnable if the file is ever lost.
      if [ ! -s ${apiTokenFile} ]; then
        echo "issuing a bootstrap API token"
        ${forgejoExe} admin user generate-access-token \
          --username ${lib.escapeShellArg cfg.adminUser} \
          --token-name "nixos-bootstrap-$(date +%s)" \
          --scopes "write:user,write:repository" \
          --raw > ${apiTokenFile}
        chmod 600 ${apiTokenFile}
      fi
      api_token="$(cat ${apiTokenFile})"

      # Every declared key, compared by content so a retitled key is not
      # duplicated (Forgejo answers 422 on a repeat and that would abort).
      register_user_key() {
        local title="$1" file="$2" content
        content="$(cat "$file")"

        if api "${localApi}/user/keys" | jq -e \
            --arg key "$content" 'any(.[]; .key == $key)' >/dev/null; then
          return 0
        fi

        echo "registering SSH key $title"
        api --request POST --data "$(jq -n \
          --arg title "$title" --arg key "$content" \
          '{ title: $title, key: $key, read_only: false }')" \
          "${localApi}/user/keys" >/dev/null
      }

      ensure_repository() {
        local name="$1"

        if api --output /dev/null \
            "${localApi}/repos/${cfg.adminUser}/$name" 2>/dev/null; then
          return 0
        fi

        echo "creating repository $name"
        # auto_init would leave a root commit that a later `git push` of real
        # history could not fast-forward over.
        api --request POST --data "$(jq -n --arg name "$name" \
          '{ name: $name, private: true, auto_init: false, default_branch: "main" }')" \
          "${localApi}/user/repos" >/dev/null
      }

      # Write access scoped to one repository, for automation that should not
      # hold the account's own key.
      ensure_deploy_key() {
        local repository="$1" title="$2" file="$3" content

        # The owning service generates this on its first start and is ordered
        # before us, so absence here means that service failed.
        if [ ! -s "$file" ]; then
          echo "deploy key $file is missing; skipping $title on $repository" >&2
          return 1
        fi
        content="$(cat "$file")"

        if api "${localApi}/repos/${cfg.adminUser}/$repository/keys" | jq -e \
            --arg key "$content" 'any(.[]; .key == $key)' >/dev/null; then
          return 0
        fi

        echo "registering deploy key $title on $repository"
        api --request POST --data "$(jq -n \
          --arg title "$title" --arg key "$content" \
          '{ title: $title, key: $key, read_only: false }')" \
          "${localApi}/repos/${cfg.adminUser}/$repository/keys" >/dev/null
      }

      register_user_key "fleet" ${fleetKeyPath}

      ${lib.concatMapStringsSep "\n" (
        name: "ensure_repository ${lib.escapeShellArg name}"
      ) cfg.repositories}

      ${lib.concatMapStringsSep "\n" (key: ''
        ensure_deploy_key ${lib.escapeShellArg key.repository} ${
          lib.escapeShellArg key.title
        } ${lib.escapeShellArg key.publicKeyFile}
      '') cfg.deployKeys}
    '';
  };
in
{
  options.forge = {
    enable = lib.mkEnableOption "Forgejo git forge, reachable over the tailnet";

    domain = lib.mkOption {
      type = lib.types.str;
      default = "omega.tail29bd65.ts.net";
      description = ''
        Hostname clients use. Fully qualified rather than the short `omega`,
        because git-lfs resolves its transfer endpoint from this value and so
        it has to work without the tailnet DNS search domain applied.
      '';
    };

    httpPort = lib.mkOption {
      type = lib.types.port;
      default = 3000;
      description = "Tailnet-only port for the web UI, API and LFS transfers.";
    };

    sshPort = lib.mkOption {
      type = lib.types.port;
      default = 2222;
      description = ''
        Tailnet-only port for git over SSH. Not 22: that belongs to the host's
        own sshd, and Forgejo runs its own SSH server rather than sharing one.
      '';
    };

    adminUser = lib.mkOption {
      type = lib.types.str;
      default = "gusjengis";
      description = "Forgejo administrator, and the owner of every repository below.";
    };

    adminEmail = lib.mkOption {
      type = lib.types.str;
      default = "anthony.j.green@outlook.com";
      description = "Administrator email address. Never sent anywhere; no mailer is configured.";
    };

    repositories = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "Wallpapers" ];
      description = ''
        Repositories created under {option}`forge.adminUser` if missing, always
        private. Removing a name here never deletes anything, so the forge
        cannot drop history because of an edit to this list.
      '';
    };

    deployKeys = lib.mkOption {
      default = [ ];
      description = ''
        Per-repository write keys for local automation. The service owning each
        key generates it and must order itself
        `before = [ "forgejo-bootstrap.service" ]`.
      '';
      type = lib.types.listOf (
        lib.types.submodule {
          options = {
            repository = lib.mkOption {
              type = lib.types.str;
              description = "Repository the key may push to.";
            };
            title = lib.mkOption {
              type = lib.types.str;
              description = "Label shown in the Forgejo UI.";
            };
            publicKeyFile = lib.mkOption {
              type = lib.types.str;
              description = "Path to the public half, read at runtime rather than by Nix.";
            };
          };
        }
      );
    };

    actions.enable = lib.mkEnableOption "Forgejo Actions and its runner registration endpoint";
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.tailscale.enable;
        message = "forge.enable serves only over the tailnet, so tailscale.enable must be true.";
      }
    ];

    services.forgejo = {
      enable = true;

      # Binary blobs belong outside the object database; the wallpaper library
      # is ~15 GB of images that would otherwise land in pack files.
      lfs.enable = true;

      # One user and a handful of repositories do not justify a database
      # server. Being a single file also makes the whole forge one `cp` away
      # from a copy, should that ever be wanted.
      database.type = "sqlite3";

      settings = {
        server = {
          DOMAIN = cfg.domain;
          ROOT_URL = "http://${cfg.domain}:${toString cfg.httpPort}/";
          HTTP_PORT = cfg.httpPort;

          # Forgejo's own SSH server rather than the host's sshd, which would
          # otherwise need a `git` user and a Forgejo-managed authorized_keys.
          START_SSH_SERVER = true;
          SSH_DOMAIN = cfg.domain;

          # Two separate settings: SSH_LISTEN_PORT is where the server binds,
          # SSH_PORT is the port printed in clone URLs. The latter defaults to
          # 22, which here is the host's sshd, so leaving it alone would hand
          # out URLs that reach the wrong daemon.
          SSH_LISTEN_PORT = cfg.sshPort;
          SSH_PORT = cfg.sshPort;

          # SSH_USER only sets the username Forgejo prints in clone URLs.
          # BUILTIN_SSH_SERVER_USER is the one its SSH server actually
          # authenticates against, and it defaults to RUN_USER ("forgejo"), so
          # without this line `git@` is refused and only `forgejo@` works.
          SSH_USER = "git";
          BUILTIN_SSH_SERVER_USER = "git";
        };

        service = {
          # Nobody else should ever get an account, and the tailnet is not a
          # trust boundary worth relying on alone.
          DISABLE_REGISTRATION = true;
        };

        repository = {
          DEFAULT_BRANCH = "main";
          DEFAULT_PRIVATE = "private";
        };

        # No runner is registered; see the note at the top of this file.
        actions.ENABLED = cfg.actions.enable;

        # Cookies travel over plain HTTP inside WireGuard, so marking them
        # secure would stop the UI from holding a session at all.
        session.COOKIE_SECURE = false;
      };
    };

    # Both ports stay invisible to the LAN and the internet. Forgejo binds
    # 0.0.0.0 (its default) and the firewall is what narrows that down, the
    # same arrangement alpha's services use.
    networking.firewall.interfaces."tailscale0".allowedTCPPorts = [
      cfg.httpPort
      cfg.sshPort
    ];

    # Generated once, on disk, rather than baked into the store where it would
    # be world readable. Only needed to log into the web UI: git access is by
    # SSH key, so this is read roughly never.
    systemd.services.forgejo-admin-password = {
      description = "Generate the Forgejo administrator password on first run";
      before = [ "forgejo-bootstrap.service" ];
      requiredBy = [ "forgejo-bootstrap.service" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        install -d -m 0750 -o forgejo -g forgejo ${stateDir}
        if [ ! -s ${adminPasswordFile} ]; then
          ${pkgs.coreutils}/bin/head -c 32 /dev/urandom \
            | ${pkgs.coreutils}/bin/base64 \
            | ${pkgs.coreutils}/bin/tr -d '+/=' > ${adminPasswordFile}
          chown forgejo:forgejo ${adminPasswordFile}
          chmod 400 ${adminPasswordFile}
        fi
      '';
    };

    # Everything a fresh disk needs before the fleet can push: an account, a
    # token, the fleet key, the declared repositories and their deploy keys.
    # Idempotent, so it simply confirms all of that on every boot.
    systemd.services.forgejo-bootstrap = {
      description = "Create the Forgejo account, keys and repositories declared in Nix";
      after = [ "forgejo.service" ];
      requires = [ "forgejo.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        User = "forgejo";
        Group = "forgejo";
        WorkingDirectory = stateDir;
        ExecStart = lib.getExe bootstrapForge;
        UMask = "0077";
      };
      environment = {
        HOME = stateDir;
        FORGEJO_WORK_DIR = stateDir;
        FORGEJO_CUSTOM = "${stateDir}/custom";
      };
    };
  };
}
