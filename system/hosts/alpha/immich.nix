{
  config,
  lib,
  pkgs,
  ...
}:

# Immich indexes the shared Pictures directory without owning the originals.
# Its database, thumbnails, and other generated state stay hidden in .services.
let
  cfg = config.immich;
  dataRoot = "/data/.services";
  mediaLocation = "${dataRoot}/immich";
  publicUrl = "https://alpha.tail29bd65.ts.net:8443";
in
{
  options = {
    immich.enable = lib.mkEnableOption "Immich photo management for /data/Pictures";
    immich.funnel.enable = lib.mkEnableOption "publicly exposes Immich with Tailscale Funnel";
  };

  config = lib.mkIf cfg.enable {
    services.immich = {
      enable = true;
      host = "127.0.0.1";
      port = 2283;
      openFirewall = false;
      inherit mediaLocation;
      user = "gusjengis";
      group = "users";

      machine-learning.enable = true;

      settings = {
        newVersionCheck.enabled = false;
        server.externalDomain = publicUrl;
      };
    };

    # Keep all service state on the locally attached data drive. Immich uses
    # its own database in the PostgreSQL cluster already shared by Nextcloud.
    services.postgresql.dataDir = "${dataRoot}/postgres/${config.services.postgresql.package.psqlSchema}";
    services.postgresql.ensureUsers = [
      {
        name = "gusjengis";
        ensureClauses.login = true;
      }
    ];
    systemd.services.postgresql-setup.serviceConfig.ExecStartPost = lib.mkAfter [
      "${lib.getExe' config.services.postgresql.package "psql"} -d immich -c 'GRANT immich TO gusjengis'"
    ];

    systemd.tmpfiles.rules = [
      "d ${dataRoot} 0751 root root -"
      "d ${mediaLocation} 0700 gusjengis users -"
      "d ${dataRoot}/postgres 0750 postgres postgres -"
      "d ${dataRoot}/postgres/${config.services.postgresql.package.psqlSchema} 0700 postgres postgres -"
    ];

    systemd.services.postgresql.unitConfig.RequiresMountsFor = [ "/data" ];
    systemd.services.immich-storage-permissions = {
      description = "Prepare Immich writable storage";
      before = [ "immich-server.service" ];
      requiredBy = [ "immich-server.service" ];
      unitConfig.RequiresMountsFor = [ "/data" ];
      serviceConfig.Type = "oneshot";
      script = ''
        ${pkgs.coreutils}/bin/chown -R gusjengis:users ${mediaLocation}
      '';
    };
    systemd.services.immich-server = {
      unitConfig.RequiresMountsFor = [ "/data" ];
      serviceConfig = {
        ProtectSystem = "strict";
        ReadWritePaths = [ mediaLocation ];
      };
    };
    systemd.services.immich-machine-learning = {
      unitConfig.RequiresMountsFor = [ "/data" ];
      serviceConfig.ProtectSystem = "strict";
    };

    # Nextcloud owns Funnel 443. Immich uses another Funnel-supported HTTPS
    # port, avoiding unsupported subpath hosting and exposing no local port.
    systemd.services.tailscale-funnel-immich = lib.mkIf cfg.funnel.enable {
      description = "Serve Immich over public HTTPS with Tailscale Funnel";
      after = [
        "tailscaled.service"
        "immich-server.service"
      ];
      requires = [ "tailscaled.service" ];
      wants = [ "immich-server.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        ExecStart = "${pkgs.tailscale}/bin/tailscale funnel --yes --https=8443 http://127.0.0.1:2283";
        ExecStop = "${pkgs.tailscale}/bin/tailscale funnel --yes --https=8443 off";
        Restart = "on-failure";
        RestartSec = 10;
      };
    };
  };
}
