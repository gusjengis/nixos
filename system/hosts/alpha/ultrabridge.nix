{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.ultrabridge;
  stateDir = "/data/.services/ultrabridge";
  fileRoot = "/data/Supernote";
  adminPasswordFile = "${stateDir}/admin-password";

  package = pkgs.buildGoModule rec {
    pname = "ultrabridge";
    version = "0-unstable-2026-08-30";

    src = pkgs.fetchFromGitHub {
      owner = "jdkruzr";
      repo = "ultrabridge";
      rev = "74efb8d64090956fb28a88130ffd375dc3094723";
      hash = "sha256-ZX/1sJga+SEcty6qsSoHyxL3Ijer94t4bEuyP1ozX1k=";
    };

    vendorHash = "sha256-O0AnTdLy+fpinzmTXKO4HDQftnzayATYuNxDqFhzV/A=";
    subPackages = [ "cmd/ultrabridge" ];

    nativeBuildInputs = [ pkgs.makeWrapper ];
    postInstall = ''
      wrapProgram "$out/bin/ultrabridge" \
        --prefix PATH : ${lib.makeBinPath [ pkgs."poppler-utils" ]}
    '';

    meta = {
      description = "Self-hosted bridge for e-ink notes, tasks, search, and AI tools";
      homepage = "https://github.com/jdkruzr/ultrabridge";
      license = lib.licenses.asl20;
      mainProgram = "ultrabridge";
    };
  };
in
{
  options.ultrabridge = {
    enable = lib.mkEnableOption "UltraBridge Supernote sync server";

    webPort = lib.mkOption {
      type = lib.types.port;
      default = 8444;
      description = "Tailnet-only HTTP port for the UltraBridge UI and API.";
    };

    adminUser = lib.mkOption {
      type = lib.types.str;
      default = "gusjengis";
      description = "Initial UltraBridge web administrator username.";
    };

    funnel = {
      enable = lib.mkEnableOption "publicly expose Supernote device sync with Tailscale Funnel";

      port = lib.mkOption {
        type = lib.types.enum [
          443
          8443
          10000
        ];
        default = 10000;
        description = "Public HTTPS Funnel port for Supernote device sync.";
      };
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.tmpfiles.rules = [
      "d /data/.services 0751 root root -"
      "d ${stateDir} 0750 gusjengis users -"
      "d ${fileRoot} 2775 gusjengis users -"
    ];

    systemd.services.ultrabridge = {
      description = "UltraBridge Supernote sync server";
      after = [
        "network-online.target"
        "tailscaled.service"
      ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
      unitConfig.RequiresMountsFor = [ "/data" ];

      environment = {
        HOME = stateDir;
        UB_DB_PATH = "${stateDir}/ultrabridge.db";
        UB_TASK_DB_PATH = "${stateDir}/ultrabridge-tasks.db";
        UB_LOG_FILE = "${stateDir}/ultrabridge.log";
        UB_LISTEN_ADDR = ":${toString cfg.webPort}";
        UB_SPC_MODE = "server";
        UB_SPC_LISTEN_ADDR = "127.0.0.1:8089";
        UB_SPC_FILE_ROOT = fileRoot;
        UB_OCR_ENABLED = "true";
        UB_OCR_API_URL = "http://omega:11434";
        UB_OCR_MODEL = "qwen3.6:35b-a3b";
        UB_OCR_FORMAT = "openai";
        UB_EMBED_ENABLED = "false";
        UB_CHAT_ENABLED = "false";
      };

      serviceConfig = {
        Type = "simple";
        ExecStart = lib.getExe package;
        Restart = "on-failure";
        RestartSec = 5;
        User = "gusjengis";
        Group = "users";
        UMask = "0002";

        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectHome = true;
        ProtectSystem = "strict";
        ReadWritePaths = [
          stateDir
          fileRoot
        ];
      };
    };

    systemd.services.ultrabridge-admin-password = {
      description = "Generate UltraBridge administrator password";
      before = [ "ultrabridge-seed-user.service" ];
      requiredBy = [ "ultrabridge-seed-user.service" ];
      unitConfig.RequiresMountsFor = [ "/data" ];
      serviceConfig.Type = "oneshot";
      script = ''
        if [ ! -s ${adminPasswordFile} ]; then
          ${pkgs.coreutils}/bin/head -c 32 /dev/urandom \
            | ${pkgs.coreutils}/bin/base64 \
            | ${pkgs.coreutils}/bin/tr -d '+/=' > ${adminPasswordFile}
          chown gusjengis:users ${adminPasswordFile}
          chmod 600 ${adminPasswordFile}
        fi
      '';
    };

    systemd.services.ultrabridge-seed-user = {
      description = "Seed UltraBridge web administrator";
      after = [ "ultrabridge.service" ];
      requires = [ "ultrabridge.service" ];
      wantedBy = [ "multi-user.target" ];
      unitConfig.RequiresMountsFor = [ "/data" ];
      environment = {
        UB_DB_PATH = "${stateDir}/ultrabridge.db";
        UB_TASK_DB_PATH = "${stateDir}/ultrabridge-tasks.db";
      };
      serviceConfig = {
        Type = "oneshot";
        User = "gusjengis";
        Group = "users";
      };
      script = ''
        for attempt in $(${pkgs.coreutils}/bin/seq 1 60); do
          if ${pkgs.curl}/bin/curl --fail --silent http://127.0.0.1:${toString cfg.webPort}/health >/dev/null; then
            password="$(${pkgs.coreutils}/bin/cat ${adminPasswordFile})"
            exec ${lib.getExe package} seed-user ${lib.escapeShellArg cfg.adminUser} "$password"
          fi
          sleep 1
        done
        echo "UltraBridge did not become healthy within 60 seconds" >&2
        exit 1
      '';
    };

    # UI traffic remains private and is already encrypted by Tailscale.
    networking.firewall.interfaces."tailscale0".allowedTCPPorts = [ cfg.webPort ];

    systemd.services.tailscale-funnel-ultrabridge = lib.mkIf cfg.funnel.enable {
      description = "Expose UltraBridge Supernote sync through Tailscale Funnel";
      after = [
        "tailscaled.service"
        "ultrabridge.service"
      ];
      requires = [
        "tailscaled.service"
        "ultrabridge.service"
      ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        ExecStart = "${pkgs.tailscale}/bin/tailscale funnel --yes --https=${toString cfg.funnel.port} http://127.0.0.1:8089";
        Restart = "on-failure";
        RestartSec = 10;
      };
    };
  };
}
