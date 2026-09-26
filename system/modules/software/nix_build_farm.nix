# Fleet build farm: one machine builds, everybody else downloads.
#
# Two roles, both declared here so a client and the server can never disagree
# about the port, the cache URL, or the signing key:
#
#   * `nixBuildFarm.server.enable` - the machine that does the building. It runs
#     Harmonia to serve its own `/nix/store` as a signed binary cache, accepts
#     remote build requests over SSH, and emulates `aarch64-linux` through
#     binfmt/QEMU so an x86_64 box can build for the Asahi laptop.
#
#   * `nixBuildFarm.client.enable` - every other machine. Adds the server as a
#     remote builder and as a *secondary* substituter, so an uncached derivation
#     is built once on the fast machine and then downloaded by everyone else.
#
# Why Harmonia and not Attic: Harmonia serves the store that is already there.
# A remote build lands in the server's store as a side effect of building, so it
# is cacheable with no push step, no separate multi-terabyte copy of every
# artifact, and no database to keep consistent with the store. Attic's chunked
# dedup and multi-cache ACLs buy nothing for a single-owner fleet on a tailnet,
# and its push-based model would need a post-build hook on every machine.
#
# Exposure is tailnet-only. Harmonia speaks plain HTTP with no authentication,
# so its port is opened on `tailscale0` and nowhere else; the transport is
# WireGuard rather than TLS. Nothing here opens a port to the LAN or internet.
#
# Priority: cache.nixos.org stays first for ordinary packages. Harmonia reports
# `priority = 50` in its nix-cache-info against cache.nixos.org's 40, and Nix
# sorts substituters by that number, so upstream is always asked first and the
# private cache only answers for things upstream does not have.
#
# Fallback when the server is down, all of it verified by black-holing the
# server's tailnet address and rebuilding:
#   * Substitution: Nix logs `unable to download ...`, disables that cache for
#     60 seconds, and carries on to cache.nixos.org or a local build. This is
#     *only* true because of `fallback = true` below, which is a correctness
#     requirement here and not a preference - see the comment on it.
#   * Remote building: Nix logs `cannot build on 'ssh-ng://...'` and builds on
#     the local machine instead. Local `max-jobs` is deliberately left at its
#     default and never set to zero, which is what leaves that fallback open.
#   * Nothing is trusted that should not be: a path still has to carry a
#     signature from `publicKey` to be accepted, down or up.
#   * The local store, the system profile, and its generations are untouched by
#     any of this. A rebuild started while the server is down simply builds
#     everything locally and takes longer.
#   * The one case with no fallback is a *foreign*-system derivation on a client
#     that cannot emulate it - an `aarch64-linux` build asked for from an x86_64
#     machine. That errors out for want of any builder, exactly as it would if
#     this module did not exist.
#   * `nixos-rebuild`, `nix build`, `home-manager`, and `nix develop` all read
#     the same daemon settings, so none of them has a separate failure mode.
{
  config,
  hostName,
  hosts,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nixBuildFarm;

  serverFqdn = "${cfg.serverHost}.${cfg.tailnetDomain}";
  cacheUrl = "http://${serverFqdn}:${toString cfg.port}";

  # The public half of the fleet SSH key, already committed for `gusjengis`'s
  # `authorizedKeys` in system/modules/users.nix. Reused rather than replaced:
  # a second keypair would have to be distributed to every machine by hand
  # before that machine could build anything.
  sharedKeyPath = ./../../keys/shared_ed25519.pub;

  buildMachine = system: speedFactor: supportedFeatures: {
    inherit
      system
      speedFactor
      supportedFeatures
      ;
    hostName = serverFqdn;
    protocol = "ssh-ng";
    sshUser = cfg.sshUser;
    sshKey = cfg.sshKey;
    maxJobs = cfg.server.maxJobs;
  };
in
{
  options.nixBuildFarm = {
    serverHost = lib.mkOption {
      type = lib.types.str;
      default = "omega";
      description = "Roster name of the machine that builds for the fleet.";
    };

    tailnetDomain = lib.mkOption {
      type = lib.types.str;
      default = config.fleetMonitor.tailnetDomain;
      defaultText = lib.literalExpression "config.fleetMonitor.tailnetDomain";
      description = ''
        MagicDNS domain the server is reached through. Deliberately a name and
        not the tailnet IP: a reinstalled node keeps its name and does not keep
        its address.
      '';
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 5000;
      description = "Harmonia's port on the server. Reachable over `tailscale0` only.";
    };

    publicKey = lib.mkOption {
      type = lib.types.str;
      default = "omega-1:nS4g8LEHslXkfqoB60ge4FpzMHqXGN0Eo5VAmb0W2SU=";
      description = ''
        Public half of the cache signing key. Safe to commit; that is what a
        public key is for. Clients refuse any path from the cache that is not
        signed by it, so this is what makes an unauthenticated HTTP cache on the
        tailnet safe to trust.

        The private half lives only on the server, at
        `nixBuildFarm.server.signKeyPath`. If the server is reinstalled and the
        private key is not restored from backup, the regenerated key will not
        match this value and `nix-cache-key.service` will fail loudly with the
        new public key printed, rather than silently serving paths no client
        will accept.
      '';
    };

    serverHostKey = lib.mkOption {
      type = lib.types.str;
      default = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGn64SLraK9sh7IPRgto0AYSIcIuD9jgYq2JXxBEaAYq";
      description = ''
        The server's SSH host key, pinned in `/etc/ssh/ssh_known_hosts` so the
        root-owned Nix daemon can connect without an interactive prompt it has
        no way to answer. Update this if the server is ever reinstalled; until
        then remote builds fail closed and fall back to building locally.
      '';
    };

    sshUser = lib.mkOption {
      type = lib.types.str;
      default = "nixremote";
      description = ''
        Account on the server that accepts build requests. A dedicated user
        rather than `gusjengis`, so the privileges a remote builder needs are
        visible in one place instead of riding along with a login account.
      '';
    };

    sshKey = lib.mkOption {
      type = lib.types.path;
      default = "/home/gusjengis/.config/secrets/ssh/shared_ed25519";
      description = ''
        Private key the Nix daemon authenticates with. Read as root out of the
        synced secrets directory; the matching public key is committed at
        system/keys/shared_ed25519.pub. A machine whose secrets are not synced
        yet simply cannot reach the builder and builds locally.
      '';
    };

    nativeSystem = lib.mkOption {
      type = lib.types.str;
      default = hosts.${cfg.serverHost}.system;
      defaultText = lib.literalExpression "hosts.\${config.nixBuildFarm.serverHost}.system";
      description = ''
        What the server builds without emulation. Taken from the roster rather
        than from this machine's own platform, because a client has to advertise
        the *server's* architecture, not its own - the Asahi laptop offloading
        `x86_64-linux` work is the case that gets this wrong otherwise.
      '';
    };

    emulatedSystems = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "aarch64-linux" ];
      description = ''
        Systems the server builds through binfmt/QEMU rather than natively.
        Read by both roles: the server registers the interpreters, and clients
        advertise the server as a builder for them.
      '';
    };

    server = {
      enable = lib.mkEnableOption "building and caching for the rest of the fleet" // {
        default = hostName == cfg.serverHost;
        defaultText = lib.literalExpression "hostName == config.nixBuildFarm.serverHost";
      };

      maxJobs = lib.mkOption {
        type = lib.types.ints.positive;
        default = 4;
        description = ''
          Derivations built at once. Four jobs of `coresPerJob = 6` saturate the
          server's 24 threads exactly, while leaving each job roughly 8 GB of
          the 32 GB installed. Raising this trades a linker or an LTO step
          getting OOM-killed for throughput that the thread count cannot
          actually deliver.
        '';
      };

      coresPerJob = lib.mkOption {
        type = lib.types.ints.positive;
        default = 6;
        description = "`$NIX_BUILD_CORES` inside each job. See `maxJobs`.";
      };

      signKeyPath = lib.mkOption {
        type = lib.types.path;
        default = "/var/lib/nix-cache/cache-priv-key.pem";
        description = ''
          Private signing key, outside the Nix store because the store is world
          readable. Mode 0400 root, handed to Harmonia through systemd's
          `LoadCredential` so the (dynamic, unprivileged) service user never
          needs access to the file itself.
        '';
      };

      keyName = lib.mkOption {
        type = lib.types.str;
        default = "omega-1";
        description = "Name embedded in a generated signing key. Must match `publicKey`'s prefix.";
      };

      minFreeGiB = lib.mkOption {
        type = lib.types.ints.positive;
        default = 50;
        description = ''
          Free space below which the daemon garbage-collects mid-build, up to
          `maxFreeGiB`. This is the continuous half of the retention policy and
          the half a cache actually wants: artifacts stay for as long as there is
          room for them and are evicted only under pressure. On a 1.8 TB disk,
          50 GiB is a comfortable floor for a single build's worth of headroom.
        '';
      };

      maxFreeGiB = lib.mkOption {
        type = lib.types.ints.positive;
        default = 200;
        description = "Free space the daemon's pressure collection stops at.";
      };

      retentionDays = lib.mkOption {
        type = lib.types.ints.positive;
        default = 30;
        description = ''
          Age at which the monthly sweep drops old profile generations. Those
          generations are GC roots, so without this a year of `nixos-rebuild`
          pins a year of closures that pressure collection is not allowed to
          touch, and the floor under the store only ever rises.

          Note what the sweep costs: `nix-collect-garbage` deletes the old
          generations *and then collects*, and a build this machine did for
          somebody else is rooted by nothing here, so anything not referenced by
          a surviving generation is dropped with them. Cache retention is
          therefore "until the next monthly sweep, or until the disk fills,
          whichever comes first" - which is the right trade for artifacts that
          every machine which asked for them already has locally, and a cheap one
          to change by raising this number.
        '';
      };
    };

    client = {
      enable = lib.mkEnableOption "offloading builds to the fleet build server" // {
        default = !cfg.server.enable;
        defaultText = lib.literalExpression "!config.nixBuildFarm.server.enable";
      };

      speedFactor = lib.mkOption {
        type = lib.types.ints.positive;
        default = 4;
        description = ''
          How much faster the server is than this machine, for native builds.
          The local machine is implicitly 1, so this is what makes Nix prefer
          the server while still using local slots when the server is busy.
        '';
      };

      emulatedSpeedFactor = lib.mkOption {
        type = lib.types.ints.positive;
        default = 1;
        description = ''
          The same, for the emulated systems. Deliberately 1: QEMU user-mode
          emulation is slower than the Asahi laptop building for itself, so the
          laptop should not hand its own native work away. An x86_64 client has
          no local alternative, so for it any positive value means "the server".
        '';
      };
    };
  };

  config = lib.mkMerge [
    {
      assertions = [
        {
          assertion = !(cfg.server.enable && cfg.client.enable);
          message = "nixBuildFarm: ${hostName} cannot be its own remote builder.";
        }
        {
          assertion = !cfg.server.enable || cfg.server.maxFreeGiB > cfg.server.minFreeGiB;
          message = "nixBuildFarm: server.maxFreeGiB must exceed server.minFreeGiB.";
        }
        {
          assertion = !(cfg.server.enable || cfg.client.enable) || config.tailscale.enable;
          message = "nixBuildFarm: the build farm is reached over the tailnet, so ${hostName} needs tailscale.enable.";
        }
      ];
    }

    (lib.mkIf cfg.server.enable {
      # Lets an x86_64 host build aarch64 derivations. The binfmt module also
      # adds these to `nix.settings.extra-platforms`, which is what makes the
      # daemon advertise them to clients as buildable.
      boot.binfmt.emulatedSystems = cfg.emulatedSystems;

      nix.settings = {
        max-jobs = cfg.server.maxJobs;
        cores = cfg.server.coresPerJob;

        # A remote builder has to be trusted to be useful: an untrusted user
        # cannot import the closure a client sends it, nor return one.
        trusted-users = [ cfg.sshUser ];

        # Sign everything built here. Harmonia signs at serve time as well, so
        # this is belt and braces - but it also covers a manual `nix copy` out
        # of this store, which Harmonia is not involved in.
        secret-key-files = [ cfg.server.signKeyPath ];

        min-free = cfg.server.minFreeGiB * 1024 * 1024 * 1024;
        max-free = cfg.server.maxFreeGiB * 1024 * 1024 * 1024;
      };

      # The scheduled half of retention: unpins old generations so the pressure
      # collection above has something it is allowed to delete. Monthly rather
      # than the usual weekly, because the same command also collects, and this
      # store is a cache worth keeping warm. See `retentionDays`.
      nix.gc = {
        automatic = true;
        dates = "monthly";
        options = "--delete-older-than ${toString cfg.server.retentionDays}d";
      };

      # Hard-links identical files between store paths. On a machine holding the
      # build output of an entire fleet this is a large, free win.
      nix.optimise = {
        automatic = true;
        dates = [ "weekly" ];
      };

      users.groups.${cfg.sshUser} = { };
      users.users.${cfg.sshUser} = {
        isSystemUser = true;
        group = cfg.sshUser;
        # `nix-store --serve` needs a writable HOME for its temporary cache
        # directory, and a real shell, because that is what Nix runs over SSH.
        home = "/var/lib/${cfg.sshUser}";
        createHome = true;
        shell = pkgs.bashInteractive;
        openssh.authorizedKeys.keys = lib.optionals (builtins.pathExists sharedKeyPath) [
          (lib.strings.removeSuffix "\n" (builtins.readFile sharedKeyPath))
        ];
      };

      # Generates the signing key on a machine that has none, and refuses to let
      # Harmonia start with a key that no client would accept. A silent mismatch
      # here is the worst failure mode available: every path would be served,
      # signed, and then rejected, for as long as nobody looked.
      systemd.services.nix-cache-key = {
        description = "Nix binary cache signing key";
        wantedBy = [ "multi-user.target" ];
        before = [
          "harmonia.service"
          "nix-daemon.service"
        ];
        requiredBy = [ "harmonia.service" ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
        script = ''
          key=${lib.escapeShellArg (toString cfg.server.signKeyPath)}

          # Owned here rather than by a tmpfiles rule: nothing orders
          # systemd-tmpfiles ahead of this unit, and the generation below needs
          # the directory to already exist.
          install -d -m 0755 -o root -g root "$(dirname "$key")"

          if [ ! -f "$key" ]; then
            echo "no signing key at $key; generating one"
            ${pkgs.nix}/bin/nix-store --generate-binary-cache-key \
              ${lib.escapeShellArg cfg.server.keyName} "$key" "$key.pub"
            chmod 0400 "$key"
            chmod 0444 "$key.pub"
          fi

          actual="$(${pkgs.nix}/bin/nix key convert-secret-to-public < "$key")"
          expected=${lib.escapeShellArg cfg.publicKey}

          if [ "$actual" != "$expected" ]; then
            echo "signing key at $key does not match nixBuildFarm.publicKey." >&2
            echo "  on disk:    $actual" >&2
            echo "  configured: $expected" >&2
            echo "Either restore the original private key from backup, or set" >&2
            echo "nixBuildFarm.publicKey to the value above and rebuild every client." >&2
            exit 1
          fi
        '';
      };

      services.harmonia.cache = {
        enable = true;
        signKeyPaths = [ cfg.server.signKeyPath ];
        settings = {
          # Socket-activated, and the service itself runs with PrivateNetwork.
          # Binding the wildcard is therefore not an exposure decision; the
          # firewall rule below is.
          bind = "[::]:${toString cfg.port}";
          # Above cache.nixos.org's 40, so Nix asks upstream first. Higher
          # number means lower precedence.
          priority = 50;
        };
      };

      networking.firewall.interfaces."tailscale0".allowedTCPPorts = [ cfg.port ];
    })

    (lib.mkIf cfg.client.enable {
      nix.distributedBuilds = true;

      nix.buildMachines = [
        (buildMachine cfg.nativeSystem cfg.client.speedFactor [
          "big-parallel"
          "benchmark"
          "kvm"
          "nixos-test"
        ])
      ]
      ++ map (
        system:
        # No `kvm` or `nixos-test` here. Those need hardware virtualisation for
        # the guest architecture, which user-mode emulation does not provide;
        # advertising them would win the scheduling and then fail the build.
        buildMachine system cfg.client.emulatedSpeedFactor [ "big-parallel" ]
      ) (lib.filter (system: system != cfg.nativeSystem) cfg.emulatedSystems);

      nix.settings = {
        # The builder substitutes a dependency it is missing from
        # cache.nixos.org itself, instead of this machine downloading it and
        # uploading it again over a domestic connection.
        builders-use-substitutes = true;

        # Appended, not assigned: nixpkgs defines cache.nixos.org in the same
        # option and both definitions merge.
        substituters = [ cacheUrl ];
        trusted-public-keys = [ cfg.publicKey ];

        # Load-bearing, not a preference. Nix's default is to treat a narinfo
        # request that cannot reach its server as a *fatal* error, and the
        # private cache is asked only for paths cache.nixos.org does not have -
        # which is precisely every uncached build. So without this, the server
        # being off turns "build it locally" into:
        #
        #   error: unable to download 'http://.../<hash>.narinfo':
        #          Could not connect to server
        #
        # on every client, for every derivation that is not already upstream.
        # With it, Nix logs the failure, disables that cache for 60 seconds, and
        # builds from source instead. Verified by blocking the server's tailnet
        # address and rebuilding.
        fallback = true;

        # How long a client waits on a cache that is not answering before giving
        # up on it. Nix then disables that cache for 60 seconds, so the wait is
        # paid roughly once per command rather than once per path - but it is
        # paid by every rebuild, so it wants to be short. Five seconds times
        # three attempts, with Nix's backoff between them, measured at about 21
        # seconds for a build while the server was black-holed, against 35 at the
        # stock five attempts.
        #
        # Three attempts rather than five also applies to cache.nixos.org, which
        # is the whole cost of this: a genuinely flaky link retries less.
        connect-timeout = 5;
        download-attempts = 3;
      };

      # The Nix daemon runs as root and connects non-interactively, so the host
      # key has to be known ahead of time or every remote build fails on a
      # prompt nobody can see.
      programs.ssh.knownHosts.${cfg.serverHost} = {
        hostNames = [
          cfg.serverHost
          serverFqdn
        ];
        publicKey = cfg.serverHostKey;
      };

      # `extraConfig` is prepended, ahead of the generated `Host *` block, so
      # this wins for the server and changes nothing else.
      #
      # Without `ConnectTimeout`, a server whose packets are black-holed - asleep
      # or off the tailnet, as opposed to refusing the connection - costs the
      # kernel's full TCP timeout before Nix gives up on the builder and builds
      # locally: measured at 2m44s to build a one-second derivation, against 21
      # with this set. Five seconds is plenty over WireGuard on a LAN.
      programs.ssh.extraConfig = ''
        Host ${cfg.serverHost} ${serverFqdn}
          ConnectTimeout 5
          ServerAliveInterval 30
          ServerAliveCountMax 4
      '';
    })
  ];
}
