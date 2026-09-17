{
  config,
  lib,
  pkgs,
  hosts,
  hostName,
  ...
}:
let
  cfg = config.fleetMonitor;
  python = pkgs.python3.withPackages (packages: [ packages.psutil ]);
  host = hosts.${hostName};
  agentConfig = builtins.toJSON {
    host = hostName;
    inherit (host) description;
    user = cfg.user;
    services = host.services or [ ];
    port = cfg.agentPort;
    interval = cfg.collectionInterval;
    max_history_bytes = cfg.maxHistoryBytes;
    owner_login = cfg.ownerLogin;
  };
  dashboardConfig = builtins.toJSON {
    hosts = lib.mapAttrsToList (name: value: {
      inherit name;
      inherit (value) description;
      services = value.services or [ ];
      address = "${name}.${cfg.tailnetDomain}";
    }) hosts;
    agent_port = cfg.agentPort;
    port = cfg.dashboardPort;
    poll_interval = cfg.pollInterval;
    alert_repeat_seconds = cfg.alertRepeatSeconds;
    summary_interval_seconds = cfg.summaryIntervalSeconds;
    ui_file = ./fleet-monitor.html;
    owner_login = cfg.ownerLogin;
  };
in
{
  options.fleetMonitor = {
    enable = lib.mkEnableOption "tailnet fleet hardware and workload monitoring" // {
      default = true;
    };
    server.enable = lib.mkEnableOption "central fleet dashboard" // {
      default = hostName == "alpha";
    };
    user = lib.mkOption {
      type = lib.types.str;
      default = "gusjengis";
      description = "User whose tmux sessions are inspected.";
    };
    tailnetDomain = lib.mkOption {
      type = lib.types.str;
      default = "tail29bd65.ts.net";
    };
    ownerLogin = lib.mkOption {
      type = lib.types.str;
      default = "gusjengis@gmail.com";
      description = "Tailscale login allowed to read fleet telemetry.";
    };
    agentPort = lib.mkOption {
      type = lib.types.port;
      default = 9191;
    };
    dashboardPort = lib.mkOption {
      type = lib.types.port;
      default = 9190;
    };
    collectionInterval = lib.mkOption {
      type = lib.types.ints.positive;
      default = 300;
      description = "Seconds between durable hardware snapshots.";
    };
    pollInterval = lib.mkOption {
      type = lib.types.ints.positive;
      default = 60;
    };
    maxHistoryBytes = lib.mkOption {
      type = lib.types.ints.positive;
      default = 25000000;
    };
    alertRepeatSeconds = lib.mkOption {
      type = lib.types.ints.positive;
      default = 21600;
    };
    summaryIntervalSeconds = lib.mkOption {
      type = lib.types.ints.positive;
      default = 21600;
    };
    secretsFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/fleet-monitor-secrets.env";
      description = "Root-owned SMTP and AI environment file on dashboard host.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      pkgs.smartmontools
      pkgs.lm_sensors
      pkgs.nvme-cli
    ];

    networking.firewall.interfaces.tailscale0.allowedTCPPorts = [
      cfg.agentPort
    ]
    ++ lib.optionals cfg.server.enable [ cfg.dashboardPort ];

    systemd.services.fleet-monitor-agent = {
      description = "Fleet hardware and workload collector";
      after = [
        "network-online.target"
        "tailscaled.service"
      ];
      wants = [
        "network-online.target"
        "tailscaled.service"
      ];
      wantedBy = [ "multi-user.target" ];
      path = with pkgs; [
        coreutils
        lm_sensors
        pciutils
        procps
        shadow
        smartmontools
        systemd
        tailscale
        tmux
        usbutils
        util-linux
      ];
      environment.FLEET_MONITOR_CONFIG = agentConfig;
      serviceConfig = {
        ExecStart = "${python}/bin/python ${./fleet-monitor-agent.py}";
        Restart = "on-failure";
        RestartSec = 5;
        StateDirectory = "fleet-monitor-agent";
        UMask = "0077";
        NoNewPrivileges = true;
        PrivateTmp = false;
        ProtectHome = "read-only";
        ProtectSystem = "strict";
        ReadWritePaths = [ "/var/lib/fleet-monitor-agent" ];
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictSUIDSGID = true;
        BindReadOnlyPaths = [ "/run/tailscale/tailscaled.sock" ];
      };
    };

    systemd.services.fleet-monitor-dashboard = lib.mkIf cfg.server.enable {
      description = "Tailnet fleet dashboard and alert manager";
      after = [
        "network-online.target"
        "tailscaled.service"
      ];
      wants = [
        "network-online.target"
        "tailscaled.service"
      ];
      wantedBy = [ "multi-user.target" ];
      path = [ pkgs.tailscale ];
      environment.FLEET_MONITOR_CONFIG = dashboardConfig;
      serviceConfig = {
        ExecStart = "${pkgs.python3}/bin/python ${./fleet-monitor-dashboard.py}";
        EnvironmentFile = "-${cfg.secretsFile}";
        Restart = "on-failure";
        RestartSec = 5;
        StateDirectory = "fleet-monitor-dashboard";
        UMask = "0077";
        DynamicUser = true;
        NoNewPrivileges = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectHome = true;
        ProtectSystem = "strict";
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictSUIDSGID = true;
        BindReadOnlyPaths = [ "/run/tailscale/tailscaled.sock" ];
      };
    };
  };
}
