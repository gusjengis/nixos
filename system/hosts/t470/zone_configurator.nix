{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.zoneConfigurator;
in
{
  options.zoneConfigurator = {
    enable = lib.mkEnableOption "Everything Presence Zone Configurator";

    image = lib.mkOption {
      type = lib.types.str;
      default = "everythingsmarthome/everything-presence-mmwave-configurator:latest";
      description = "OCI image for the Everything Presence Zone Configurator.";
    };

    dataDir = lib.mkOption {
      type = lib.types.path;
      default = /var/lib/zone-configurator;
      description = "Persistent Zone Configurator data directory mounted at /config.";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 42069;
      description = "Zone Configurator web port.";
    };

    homeAssistantUrl = lib.mkOption {
      type = lib.types.str;
      default = "http://127.0.0.1:8123";
      description = "Base URL Zone Configurator uses to reach Home Assistant.";
    };

    tokenEnvFile = lib.mkOption {
      type = lib.types.str;
      default = "/home/gusjengis/.config/secrets/api_keys/env_vars";
      description = "Environment file containing HA_LONG_LIVED_TOKEN for Zone Configurator.";
    };
  };

  config = lib.mkIf cfg.enable {
    virtualisation.oci-containers = {
      backend = "podman";
      containers.zone-configurator = {
        image = cfg.image;
        autoStart = true;
        volumes = [
          "${toString cfg.dataDir}:/config"
        ];
        environment = {
          HA_BASE_URL = cfg.homeAssistantUrl;
          PORT = toString cfg.port;
        };
        environmentFiles = [ cfg.tokenEnvFile ];
        extraOptions = [
          "--network=host"
        ];
      };
    };

    systemd.tmpfiles.rules = [
      "d ${toString cfg.dataDir} 0750 root root -"
    ];

    systemd.services.podman-zone-configurator = {
      after = [ "podman-homeassistant.service" ];
      wants = [ "podman-homeassistant.service" ];
      preStart = ''
        if [ ! -r ${lib.escapeShellArg cfg.tokenEnvFile} ]; then
          echo "Zone Configurator token env file is missing or unreadable: ${cfg.tokenEnvFile}" >&2
          exit 1
        fi

        set -a
        . ${lib.escapeShellArg cfg.tokenEnvFile}
        set +a

        if [ -z "''${HA_LONG_LIVED_TOKEN:-}" ]; then
          echo "Zone Configurator requires HA_LONG_LIVED_TOKEN in ${cfg.tokenEnvFile}" >&2
          exit 1
        fi

        for _ in {1..120}; do
          if ${lib.getExe pkgs.curl} --fail --silent --show-error --max-time 2 ${lib.escapeShellArg cfg.homeAssistantUrl} >/dev/null; then
            exit 0
          fi
          ${lib.getExe' pkgs.coreutils "sleep"} 2
        done

        echo "Timed out waiting for Home Assistant at ${cfg.homeAssistantUrl}" >&2
        exit 1
      '';
    };

    networking.firewall.allowedTCPPorts = [ cfg.port ];
  };
}
