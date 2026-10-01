# Fleet build-farm client. Uncached derivations are offloaded to Omega over
# SSH, then downloaded from its signed Harmonia cache over the tailnet.
{
  config,
  hostName,
  hosts,
  lib,
  ...
}:
let
  cfg = config.nixBuildFarm;
  serverFqdn = "${cfg.serverHost}.${cfg.tailnetDomain}";
  cacheUrl = "http://${serverFqdn}:${toString cfg.port}";

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
    maxJobs = cfg.maxJobs;
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
      description = "MagicDNS domain through which clients reach the server.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 5000;
      description = "Harmonia port on the server.";
    };

    publicKey = lib.mkOption {
      type = lib.types.str;
      default = "omega-1:nS4g8LEHslXkfqoB60ge4FpzMHqXGN0Eo5VAmb0W2SU=";
      description = "Public key used to verify paths from the fleet cache.";
    };

    serverHostKey = lib.mkOption {
      type = lib.types.str;
      default = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGn64SLraK9sh7IPRgto0AYSIcIuD9jgYq2JXxBEaAYq";
      description = "Pinned SSH host key for the build server.";
    };

    sshUser = lib.mkOption {
      type = lib.types.str;
      default = "nixremote";
      description = "Account that accepts remote build requests.";
    };

    sshKey = lib.mkOption {
      type = lib.types.path;
      default = "/home/gusjengis/.config/secrets/ssh/shared_ed25519";
      description = "Private key used by the Nix daemon to reach the builder.";
    };

    nativeSystem = lib.mkOption {
      type = lib.types.str;
      default = hosts.${cfg.serverHost}.system;
      defaultText = lib.literalExpression "hosts.\${config.nixBuildFarm.serverHost}.system";
      description = "System the build server supports without emulation.";
    };

    emulatedSystems = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "aarch64-linux" ];
      description = "Systems the build server supports through binfmt/QEMU.";
    };

    maxJobs = lib.mkOption {
      type = lib.types.ints.positive;
      default = 4;
      description = "Concurrent jobs advertised for the remote builder.";
    };

    client = {
      enable = lib.mkEnableOption "offloading builds to the fleet build server" // {
        default = hostName != cfg.serverHost;
        defaultText = lib.literalExpression "hostName != config.nixBuildFarm.serverHost";
      };

      speedFactor = lib.mkOption {
        type = lib.types.ints.positive;
        default = 4;
        description = "Relative builder speed for native builds.";
      };

      emulatedSpeedFactor = lib.mkOption {
        type = lib.types.ints.positive;
        default = 1;
        description = "Relative builder speed for emulated systems.";
      };
    };
  };

  config = lib.mkIf cfg.client.enable {
    assertions = [
      {
        assertion = config.tailscale.enable;
        message = "nixBuildFarm: the build farm is reached over the tailnet, so ${hostName} needs tailscale.enable.";
      }
    ];

    nix.distributedBuilds = true;

    nix.buildMachines = [
      (buildMachine cfg.nativeSystem cfg.client.speedFactor [
        "big-parallel"
        "benchmark"
        "kvm"
        "nixos-test"
      ])
    ]
    ++
      map
        (
          system:
          # User-mode emulation cannot provide hardware virtualisation.
          buildMachine system cfg.client.emulatedSpeedFactor [ "big-parallel" ]
        )
        (
          lib.filter (
            system: system != cfg.nativeSystem && system != config.nixpkgs.hostPlatform.system
          ) cfg.emulatedSystems
        );

    nix.settings = {
      builders-use-substitutes = true;
      substituters = [ cacheUrl ];
      trusted-public-keys = [ cfg.publicKey ];

      # Keep local builds available when Omega or its cache is offline.
      fallback = true;
      connect-timeout = 5;
      download-attempts = 3;
    };

    programs.ssh.knownHosts.${cfg.serverHost} = {
      hostNames = [
        cfg.serverHost
        serverFqdn
      ];
      publicKey = cfg.serverHostKey;
    };

    programs.ssh.extraConfig = ''
      Host ${cfg.serverHost} ${serverFqdn}
        ConnectTimeout 5
        ServerAliveInterval 30
        ServerAliveCountMax 4
    '';
  };
}
