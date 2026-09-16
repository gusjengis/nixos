{
  config,
  pkgs,
  lib,
  inputs,
  ...
}:

let
  hacs =
    pkgs.runCommand "hacs-2.0.5"
      {
        src = pkgs.fetchurl {
          url = "https://github.com/hacs/integration/releases/download/2.0.5/hacs.zip";
          hash = "sha256-l75rgkpPOOaDcozG3XI2f2uLrQpDQosbO5h6MIet9BM=";
        };
        nativeBuildInputs = [ pkgs.unzip ];
      }
      ''
        mkdir -p "$out"
        unzip "$src" -d "$out"
      '';
in
{
  options = {
    homeAssistant.enable = lib.mkEnableOption "enables hyprland";
  };

  config = lib.mkIf config.homeAssistant.enable {
    virtualisation.oci-containers = {
      backend = "podman";
      containers.homeassistant = {
        volumes = [
          "home-assistant:/config"
          "${hacs}:/config/custom_components/hacs:ro"
          "/run/dbus:/run/dbus:ro"
        ];
        environment.TZ = "America/Los_Angeles";
        image = "ghcr.io/home-assistant/home-assistant:stable"; # Warning: if the tag does not change, the image will not be updated
        extraOptions = [
          "--network=host"
        ];
      };
    };

    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
    };

    systemd.services."podman-homeassistant" = {
      after = [ "bluetooth.service" ];
      wants = [ "bluetooth.service" ];
    };

    networking.firewall.allowedTCPPorts = [
      8123 # webU
      5580 # matter
    ];

    networking.firewall.allowedUDPPorts = [
      5353 # mDNS / Zeroconf
      1900 # SSDP / UPnP
    ];

    services.matter-server.enable = true;
    nixpkgs.config.permittedInsecurePackages = [
      "openssl-1.1.1w" # supposedly matter needs this
    ];
  };
}
