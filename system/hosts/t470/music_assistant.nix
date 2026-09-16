{
  config,
  lib,
  pkgs,
  ...
}:

let
  resolvConf = pkgs.writeText "music-assistant-resolv.conf" "nameserver 1.1.1.1\nnameserver 8.8.8.8\noptions edns0\n";
  # Pin the official 2.10.3 stable image and overlay our fork of the same commit on top of
  # it, so the baked dependencies (music-assistant-models, aiohttp, yt-dlp, ...) are exactly
  # the ones the fork was built and tested against.
  musicAssistantImage = "ghcr.io/music-assistant/server@sha256:885872224fa541c0faefc936625c939ba705a00e89c180f89e877f58448ea5d5";

  # Music Assistant 2.10.3 plus the YouTube Music Free provider, plain YouTube links, and
  # play_media's start_index (which the custom frontend below needs).
  musicAssistantFork = pkgs.fetchFromGitHub {
    owner = "gusjengis";
    repo = "mass-server";
    rev = "b4e39bab316098ba8437a26e9f03f69f8af93fe5";
    hash = "sha256-G2kFmDfmAy0FgVY/oxzw1FHpc21p9T+kSOC3lMlhyZ0=";
  };

  frontendSrc = pkgs.fetchFromGitHub {
    owner = "gusjengis";
    repo = "frontend";
    rev = "8de9a520874f48088c09a0a5b7b9fe36beb9a0ba";
    hash = "sha256-bKnz8NhGzR4yIchoSJH7h8N3zPMwznj3XLK9Odt7318=";
  };

  # The frontend the server ships is a Python package that is really just the built bundle,
  # so building the fork's bundle and mounting it over that package swaps the UI out. It is
  # the 2.17.297 bundle the pinned image carries, plus playing a whole listing from a
  # track's play button.
  musicAssistantFrontend = pkgs.stdenv.mkDerivation (finalAttrs: {
    pname = "music-assistant-frontend";
    version = "2.17.297-library-context-queue";
    src = frontendSrc;

    nativeBuildInputs = [
      pkgs.nodejs
      pkgs.pnpm
      pkgs.pnpmConfigHook
    ];

    pnpmDeps = pkgs.fetchPnpmDeps {
      inherit (finalAttrs) pname version src;
      fetcherVersion = 4;
      hash = "sha256-cfrOczBGPcaENfXJkuXNrtqyzJ4Gttvz4wyEeH22A1g=";
    };

    buildPhase = ''
      runHook preBuild
      pnpm build
      runHook postBuild
    '';

    # vite writes the bundle straight into the layout the Python package uses
    # (index.html + assets/ beside __init__.py), which is what gets mounted.
    installPhase = ''
      runHook preInstall
      mkdir -p "$out"
      cp -r music_assistant_frontend/. "$out/"
      runHook postInstall
    '';
  });

  sitePackages = "/app/venv/lib/python3.14/site-packages";
  serverPackage = "${sitePackages}/music_assistant";
  serverMounts = [
    "-v ${musicAssistantFork}/music_assistant/controllers/music/controller.py:${serverPackage}/controllers/music/controller.py:ro"
    "-v ${musicAssistantFork}/music_assistant/controllers/player_queues/controller.py:${serverPackage}/controllers/player_queues/controller.py:ro"
    "-v ${musicAssistantFork}/music_assistant/controllers/player_queues/queue_loader.py:${serverPackage}/controllers/player_queues/queue_loader.py:ro"
    "-v ${musicAssistantFork}/music_assistant/helpers/uri.py:${serverPackage}/helpers/uri.py:ro"
    "-v ${musicAssistantFork}/music_assistant/providers/ytmusic_free:${serverPackage}/providers/ytmusic_free:ro"
  ];
in
{
  options = {
    musicAssistant.enable = lib.mkEnableOption "enables Music Assistant";
  };

  config = lib.mkIf config.musicAssistant.enable {
    virtualisation.docker.enable = true;

    systemd.services.musicassistant = {
      description = "Music Assistant";
      after = [
        "docker.service"
        "network-online.target"
      ]
      ++ lib.optionals config.tailscale.enable [ "tailscaled.service" ];
      wants = [
        "docker.service"
        "network-online.target"
      ]
      ++ lib.optionals config.tailscale.enable [ "tailscaled.service" ];
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "simple";
        Restart = "always";
        RestartSec = 10;
        ExecStartPre = "-${lib.getExe pkgs.docker} rm -f musicassistant";
        ExecStart = "${lib.getExe pkgs.docker} run --name=musicassistant --rm --pull=missing --network=host --privileged -v music-assistant:/data -v ${resolvConf}:/etc/resolv.conf:ro ${lib.concatStringsSep " " serverMounts} -v ${musicAssistantFrontend}:${sitePackages}/music_assistant_frontend:ro -e TZ=America/Los_Angeles ${musicAssistantImage}";
        ExecStop = "${lib.getExe pkgs.docker} stop musicassistant";
        ExecStopPost = "-${lib.getExe pkgs.docker} rm -f musicassistant";
      };
    };

    networking.firewall.allowedTCPPorts = [
      8095 # web UI
    ];

    networking.firewall.allowedUDPPorts = [
      5353 # mDNS / Zeroconf
      1900 # SSDP / UPnP
    ];
  };
}
