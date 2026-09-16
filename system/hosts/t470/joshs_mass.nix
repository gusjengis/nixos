{
  config,
  lib,
  pkgs,
  ...
}:

let
  tailscaleContainer = "joshs-mass-tailscale";

  resolvConf = pkgs.writeText "joshs-mass-resolv.conf" ''
    nameserver 1.1.1.1
    nameserver 8.8.8.8
    options edns0
  '';

  # Pin an image whose baked dependencies match the overlaid Music Assistant
  # fork. In particular, this digest contains music-assistant-models 1.1.136
  # and aiohttp 3.14.1, which the fork currently requires.
  musicAssistantImage = "ghcr.io/music-assistant/server@sha256:c3ae4f8d0a9a6adaa5fabf000e31d0e558c71a6c7321117be3af98e68f4c6e43";

  musicAssistantFork = pkgs.fetchFromGitHub {
    owner = "gusjengis";
    repo = "mass-server";
    rev = "05e796764c526a6a86d1ed4bdf7c48d8862ebe22";
    hash = "sha256-ilmcIzaBne/29U1WzmZ7vGv9wdJ2MflYI1RCHyvxw6I=";
  };

  configureSettings = pkgs.writeText "joshs-mass-configure.py" ''
    import json
    import os
    from pathlib import Path

    mass_ip = os.environ["MASS_IP"]

    settings_path = Path("/data/settings.json")
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
    else:
        settings = {}

    core = settings.setdefault("core", {})
    webserver = core.setdefault("webserver", {"domain": "webserver"})
    webserver.setdefault("domain", "webserver")
    webserver_values = webserver.setdefault("values", {})
    webserver_values.update({
        "bind_ip": "0.0.0.0",
        "bind_port": 8096,
        "base_url": f"http://{mass_ip}:8096",
    })

    streams = core.setdefault("streams", {"domain": "streams"})
    streams.setdefault("domain", "streams")
    streams_values = streams.setdefault("values", {})
    streams_values.update({
        "bind_ip": "0.0.0.0",
        "bind_port": 8098,
        "publish_ip": mass_ip,
    })

    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
  '';
in
{
  options = {
    joshsMass = {
      enable = lib.mkEnableOption "enables Josh's Music Assistant";
      tailscaleHostname = lib.mkOption {
        type = lib.types.str;
        default = "joshs-mass";
        description = "Tailscale hostname for Josh's Music Assistant.";
      };
      tailscaleAuthEnvFile = lib.mkOption {
        type = lib.types.str;
        default = "/home/gusjengis/.config/secrets/api_keys/env_vars";
        description = "Environment file containing TAILSCALE_AUTH_KEY for the Josh Music Assistant Tailscale node.";
      };
    };
  };

  config = lib.mkIf config.joshsMass.enable {
    virtualisation.docker.enable = true;

    systemd.services.joshs-mass-tailscale = {
      description = "Josh's Music Assistant Tailscale node";
      after = [
        "docker.service"
        "network-online.target"
      ];
      wants = [
        "docker.service"
        "network-online.target"
      ];
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "simple";
        Restart = "always";
        RestartSec = 10;
        ExecStartPre = "-${lib.getExe pkgs.docker} rm -f ${tailscaleContainer}";
        ExecStart = "${pkgs.writeShellScript "joshs-mass-tailscale-start" ''
          set -eu

          auth_args=()
          if [ -f ${lib.escapeShellArg config.joshsMass.tailscaleAuthEnvFile} ]; then
            set -a
            . ${lib.escapeShellArg config.joshsMass.tailscaleAuthEnvFile}
            set +a
          fi

          if [ -n "''${TAILSCALE_AUTH_KEY:-}" ]; then
            auth_args=(-e "TS_AUTHKEY=$TAILSCALE_AUTH_KEY")
          fi

          exec ${lib.getExe pkgs.docker} run \
            --name=${tailscaleContainer} \
            --rm \
            --pull=missing \
            --hostname=${lib.escapeShellArg config.joshsMass.tailscaleHostname} \
            --cap-add=NET_ADMIN \
            --device=/dev/net/tun \
            -v joshs-mass-tailscale:/var/lib/tailscale \
            -v ${resolvConf}:/etc/resolv.conf:ro \
            -e TS_STATE_DIR=/var/lib/tailscale \
            -e TS_USERSPACE=false \
            -e "TS_EXTRA_ARGS=--accept-dns=false --netfilter-mode=off" \
            "''${auth_args[@]}" \
            tailscale/tailscale:latest
        ''}";
        ExecStop = "${lib.getExe pkgs.docker} stop ${tailscaleContainer}";
        ExecStopPost = "-${lib.getExe pkgs.docker} rm -f ${tailscaleContainer}";
      };
    };

    systemd.services.joshs-mass = {
      description = "Josh's Music Assistant";
      requires = [ "joshs-mass-tailscale.service" ];
      after = [
        "joshs-mass-tailscale.service"
        "docker.service"
        "network-online.target"
      ]
      ++ lib.optionals config.tailscale.enable [ "tailscaled.service" ];
      wants = [
        "joshs-mass-tailscale.service"
        "docker.service"
        "network-online.target"
      ]
      ++ lib.optionals config.tailscale.enable [ "tailscaled.service" ];
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "simple";
        Restart = "always";
        RestartSec = 10;
        ExecStartPre = [
          "-${lib.getExe pkgs.docker} rm -f joshs-mass"
          "${pkgs.writeShellScript "joshs-mass-configure" ''
            set -eu

            for _ in {1..60}; do
              mass_ip="$(${lib.getExe pkgs.docker} exec ${tailscaleContainer} tailscale ip -4 2>/dev/null || true)"
              if [ -n "$mass_ip" ]; then
                break
              fi
              ${lib.getExe' pkgs.coreutils "sleep"} 2
            done

            if [ -z "''${mass_ip:-}" ]; then
              echo "Timed out waiting for ${tailscaleContainer} to get a Tailscale IPv4 address" >&2
              exit 1
            fi

            ${lib.getExe pkgs.docker} run --rm --pull=missing --network=container:${tailscaleContainer} --entrypoint /app/venv/bin/python -v joshs-mass:/data -v ${configureSettings}:/configure.py:ro -v ${resolvConf}:/etc/resolv.conf:ro -e MASS_IP="$mass_ip" ${musicAssistantImage} /configure.py
          ''}"
        ];
        ExecStart = "${lib.getExe pkgs.docker} run --name=joshs-mass --rm --pull=missing --network=container:${tailscaleContainer} --privileged -v joshs-mass:/data -v ${resolvConf}:/etc/resolv.conf:ro -v ${musicAssistantFork}/music_assistant:/app/venv/lib/python3.14/site-packages/music_assistant:ro -e TZ=America/Los_Angeles ${musicAssistantImage}";
        ExecStop = "${lib.getExe pkgs.docker} stop joshs-mass";
        ExecStopPost = "-${lib.getExe pkgs.docker} rm -f joshs-mass";
      };
    };
  };
}
