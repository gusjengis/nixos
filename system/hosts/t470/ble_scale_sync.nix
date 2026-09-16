{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.bleScaleSync;
  localBroker = cfg.mqtt.enable && cfg.mqtt.manageBroker;
  yaml = pkgs.formats.yaml { };
  settings = lib.recursiveUpdate (
    {
      version = 1;
      scale = {
        weight_unit = "kg";
        height_unit = "cm";
      };
      runtime = {
        continuous_mode = true;
        scan_cooldown = 30;
        dry_run = true;
        debug = true;
      };
      update_check = false;
    }
    // lib.optionalAttrs cfg.mqtt.enable {
      global_exporters = [
        {
          type = "mqtt";
          broker_url = cfg.mqtt.brokerUrl;
          topic = cfg.mqtt.topic;
          qos = 1;
          retain = true;
          client_id = "ble-scale-sync";
          ha_discovery = true;
          ha_device_name = cfg.mqtt.deviceName;
        }
      ];
    }
  ) cfg.settings;
  configFile = yaml.generate "ble-scale-sync-config.yaml" settings;
in
{
  options.bleScaleSync = {
    enable = lib.mkEnableOption "BLE smart scale discovery and synchronization";

    image = lib.mkOption {
      type = lib.types.str;
      default = "ghcr.io/kristianp26/ble-scale-sync@sha256:0fd038c4b745eca4ef99c5d6e6ae4f4773b8367a525fdf40159bd47c6ebb2a99";
      description = "Pinned amd64 BLE Scale Sync OCI image.";
    };

    dataDir = lib.mkOption {
      type = lib.types.path;
      default = /var/lib/ble-scale-sync;
      description = "Persistent directory for exporter authentication state.";
    };

    settings = lib.mkOption {
      type = lib.types.attrs;
      default = { };
      description = "BLE Scale Sync configuration merged with safe discovery defaults.";
    };

    mqtt = {
      enable = lib.mkEnableOption "MQTT export with Home Assistant discovery";

      brokerUrl = lib.mkOption {
        type = lib.types.str;
        default = "mqtt://127.0.0.1:1883";
        description = "MQTT broker URL used by BLE Scale Sync.";
      };

      topic = lib.mkOption {
        type = lib.types.str;
        default = "scale/body-composition";
        description = "MQTT topic for scale measurements.";
      };

      deviceName = lib.mkOption {
        type = lib.types.str;
        default = "BLE Scale";
        description = "Device name exposed through Home Assistant MQTT discovery.";
      };

      manageBroker = lib.mkOption {
        type = lib.types.bool;
        default = true;
        description = "Run a localhost-only Mosquitto broker for BLE Scale Sync and Home Assistant.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = (settings.users or [ ]) != [ ];
        message = "bleScaleSync.settings.users must contain at least one user.";
      }
    ];

    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
    };

    services.mosquitto = lib.mkIf localBroker {
      enable = true;
      listeners = [
        {
          address = "127.0.0.1";
          port = 1883;
          omitPasswordAuth = true;
          acl = [ "topic readwrite #" ];
          settings.allow_anonymous = true;
        }
      ];
    };

    systemd.tmpfiles.rules = [
      "d ${toString cfg.dataDir} 0750 1000 1000 -"
    ];

    virtualisation.oci-containers.containers.ble-scale-sync = {
      image = cfg.image;
      autoStart = true;
      volumes = [
        "${configFile}:/app/config.yaml:ro"
        "${toString cfg.dataDir}:/app/garmin-tokens"
        "/run/dbus:/run/dbus:ro"
      ];
      devices = [ "/dev/rfkill:/dev/rfkill" ];
      extraOptions = [
        "--network=host"
        "--cap-add=NET_ADMIN"
        "--cap-add=NET_RAW"
        "--group-add=0"
      ];
    };

    systemd.services.podman-ble-scale-sync = {
      after = [ "bluetooth.service" ] ++ lib.optionals localBroker [ "mosquitto.service" ];
      requires = [ "bluetooth.service" ] ++ lib.optionals localBroker [ "mosquitto.service" ];
      serviceConfig = {
        Restart = lib.mkForce "always";
        RestartSec = 5;
      };
    };
  };
}
