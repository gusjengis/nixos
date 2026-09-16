{
  config,
  lib,
  pkgs,
  ...
}:

# Nextcloud, serving the shared data drive over the tailnet.
#
# - Web UI / apps at https://alpha.tail29bd65.ts.net (TLS via tailscale serve,
#   or public internet access when nextcloud.funnel.enable is set)
# - App state, database, and secrets live on the RAID mirror in /data/.services
# - The whole drive is exposed in the web UI as a "/data" folder via the
#   files_external app. Nextcloud sees the drive through a bindfs view at
#   /mnt/nextcloud-data that maps gusjengis <-> nextcloud, so files created
#   from the web UI land on disk as gusjengis:users (same owner the NFS
#   clients use) and everything stays writable from both sides.
let
  nextcloudHostName = "alpha.tail29bd65.ts.net";
  publicShareSettings = {
    # Public links should not become permanent internet-published URLs by accident.
    shareapi_default_expire_date = true;
    shareapi_expire_after_n_days = 30;
    shareapi_enforce_expire_date = true;
  };
in
{
  options = {
    nextcloud.enable = lib.mkEnableOption "enables Nextcloud serving /data";
    nextcloud.funnel.enable = lib.mkEnableOption "publicly exposes Nextcloud with Tailscale Funnel";
  };

  config = lib.mkIf config.nextcloud.enable {
    services.nextcloud = {
      enable = true;
      package = pkgs.nextcloud33;
      hostName = nextcloudHostName;
      https = true;
      datadir = "/data/.services/nextcloud";
      maxUploadSize = "16G";
      configureRedis = true;
      database.createLocally = true;

      config = {
        dbtype = "pgsql";
        adminuser = "gusjengis";
        adminpassFile = "/data/.services/secrets/nextcloud_admin_pass";
      };

      settings = {
        trusted_domains = [
          "alpha"
          nextcloudHostName
        ];
        # pick up files changed outside nextcloud (NFS writes) on access
        filesystem_check_changes = 1;
        default_phone_region = "US";
      }
      // lib.optionalAttrs config.nextcloud.funnel.enable publicShareSettings;
    };

    # database on the mirror too
    services.postgresql.dataDir = "/data/.services/postgres/${config.services.postgresql.package.psqlSchema}";

    systemd.tmpfiles.rules = [
      "d /data/.services 0751 root root -"
      "d /data/.services/postgres 0750 postgres postgres -"
      "d /data/.services/postgres/${config.services.postgresql.package.psqlSchema} 0700 postgres postgres -"
    ];

    # bindfs view of /data for nextcloud with uid/gid mapping
    system.fsPackages = [ pkgs.bindfs ];

    fileSystems."/mnt/nextcloud-data" = {
      device = "/data";
      fsType = "fuse.bindfs";
      options = [
        "map=gusjengis/nextcloud:@users/@nextcloud"
        "nofail"
        "x-systemd.requires-mounts-for=/data"
      ];
    };

    # blank out service state inside the nextcloud view so the web UI
    # never indexes (or deletes) its own internals
    fileSystems."/mnt/nextcloud-data/.services" = {
      device = "tmpfs";
      fsType = "tmpfs";
      options = [
        "ro"
        "size=4k"
        "mode=0000"
        "nofail"
      ];
    };

    # generate the admin password once, on the drive, on first run
    systemd.services.nextcloud-admin-pass = {
      description = "Generate Nextcloud admin password on first run";
      before = [ "nextcloud-setup.service" ];
      requiredBy = [ "nextcloud-setup.service" ];
      unitConfig.RequiresMountsFor = [ "/data" ];
      serviceConfig.Type = "oneshot";
      script = ''
        install -d -m 750 -o root -g nextcloud /data/.services/secrets
        pass=/data/.services/secrets/nextcloud_admin_pass
        if [ ! -s "$pass" ]; then
          ${pkgs.coreutils}/bin/head -c 32 /dev/urandom | ${pkgs.coreutils}/bin/base64 | ${pkgs.coreutils}/bin/tr -d '+/=' > "$pass"
          chown root:nextcloud "$pass"
          chmod 440 "$pass"
        fi
      '';
    };

    # register the drive as external storage in nextcloud (idempotent)
    systemd.services.nextcloud-data-mount = {
      description = "Register /data as Nextcloud external storage";
      after = [ "nextcloud-setup.service" ];
      wants = [ "nextcloud-setup.service" ];
      wantedBy = [ "multi-user.target" ];
      unitConfig.RequiresMountsFor = [ "/mnt/nextcloud-data" ];
      serviceConfig.Type = "oneshot";
      script = ''
        occ=${config.services.nextcloud.occ}/bin/nextcloud-occ
        jq=${pkgs.jq}/bin/jq
        $occ app:enable files_external
        id="$($occ files_external:list --output=json | $jq -r 'map(select(.mount_point == "/data")) | .[0].mount_id // empty')"
        if [ -z "$id" ]; then
          $occ files_external:create "/data" local "null::null" -c datadir=/mnt/nextcloud-data
          id="$($occ files_external:list --output=json | $jq -r 'map(select(.mount_point == "/data")) | .[0].mount_id // empty')"
        fi
        # external storages don't allow sharing unless told to
        $occ files_external:option "$id" enable_sharing true
      '';
    };

    # HTTPS via Tailscale: private tailnet-only Serve by default, public Funnel when enabled.
    systemd.services.tailscale-serve-nextcloud = {
      description =
        if config.nextcloud.funnel.enable then
          "Serve Nextcloud over public HTTPS with Tailscale Funnel"
        else
          "Serve Nextcloud over HTTPS on the tailnet";
      after = [
        "tailscaled.service"
        "nginx.service"
      ];
      requires = [ "tailscaled.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        ExecStart =
          if config.nextcloud.funnel.enable then
            "${pkgs.tailscale}/bin/tailscale funnel --yes --https=443 http://127.0.0.1:80"
          else
            "${pkgs.tailscale}/bin/tailscale serve --https=443 http://127.0.0.1:80";
        Restart = "on-failure";
        RestartSec = 10;
      };
    };

    # plain-http fallback, tailnet only
    networking.firewall.interfaces."tailscale0".allowedTCPPorts = [ 80 ];

    # nothing nextcloud-related should start before the drive is up
    systemd.services.postgresql.unitConfig.RequiresMountsFor = [ "/data" ];
    systemd.services.nextcloud-setup.unitConfig.RequiresMountsFor = [ "/data" ];
    systemd.services.phpfpm-nextcloud.unitConfig.RequiresMountsFor = [
      "/data"
      "/mnt/nextcloud-data"
    ];
  };
}
