{
  config,
  hostName,
  lib,
  pkgs,
  ...
}:
{

  options = {
    tailscale.enable = lib.mkEnableOption "enables tailscale";
    tailscale.advertiseRoutes = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "192.168.122.18/32" ];
      description = ''
        Subnet routes advertised to the tailnet. Every consumer adds to this
        single list so the routes are published by one unit; separate units
        calling `tailscale set --advertise-routes` would overwrite each other.
      '';
    };
  };

  config = lib.mkIf config.tailscale.enable {
    services.tailscale = {
      enable = true;
      openFirewall = true;
      useRoutingFeatures =
        if config.tailscale.advertiseRoutes != [ ] then "both" else lib.mkDefault "client";
    };

    environment.systemPackages = with pkgs; [
      xwayland-satellite
      waypipe
    ];

    # graphics so remote guis work
    hardware.graphics.enable = true;
    hardware.graphics.enable32Bit = pkgs.stdenv.hostPlatform.isx86;

    # create a oneshot job to authenticate to Tailscale
    systemd.services.tailscale-autoconnect = {
      description = "Automatic connection to Tailscale";

      # make sure tailscale is running before trying to connect to tailscale
      after = [
        "network-pre.target"
        "tailscaled.service"
      ];
      wants = [
        "network-pre.target"
        "tailscaled.service"
      ];
      wantedBy = [ "multi-user.target" ];

      # set this service as a oneshot job
      serviceConfig.Type = "oneshot";

      # have the job run this shell script
      script = with pkgs; ''
        # A daemon restart can briefly report NoState even when this node is
        # authenticated. Wait instead of treating that transient state as a
        # fresh login and calling `tailscale up` against existing preferences.
        for _ in $(${coreutils}/bin/seq 1 30); do
          status="$(${tailscale}/bin/tailscale status -json 2>/dev/null | ${jq}/bin/jq -r .BackendState 2>/dev/null || true)"
          case "$status" in
            Running)
              ${tailscale}/bin/tailscale set --hostname=${lib.escapeShellArg hostName} --accept-routes=true
              exit 0
              ;;
            NeedsLogin)
              break
              ;;
          esac
          sleep 1
        done

        # otherwise authenticate with tailscale
        if [ -f /home/gusjengis/.config/secrets/api_keys/env_vars ]; then
          source /home/gusjengis/.config/secrets/api_keys/env_vars
        fi

        if [ -z "''${TAILSCALE_AUTH_KEY:-}" ]; then
          echo "TAILSCALE_AUTH_KEY missing; skipping tailscale up"
          exit 0
        fi


        TS_AUTHKEY="$TAILSCALE_AUTH_KEY" ${tailscale}/bin/tailscale up --reset \
          --hostname=${lib.escapeShellArg hostName} --accept-routes=true
        # --ssh --accept-dns=true
      '';
    };

    # single writer for --advertise-routes; consumers append to
    # tailscale.advertiseRoutes instead of running `tailscale set` themselves
    systemd.services.tailscale-advertise-routes = lib.mkIf (config.tailscale.advertiseRoutes != [ ]) {
      description = "Advertise subnet routes to the tailnet";
      after = [
        "tailscaled.service"
        "tailscale-autoconnect.service"
      ];
      requires = [ "tailscaled.service" ];
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${pkgs.tailscale}/bin/tailscale set --advertise-routes=${lib.concatStringsSep "," config.tailscale.advertiseRoutes}";
        Restart = "on-failure";
        RestartSec = 10;
      };
    };

    # turn on ssh!
    services.openssh = {
      enable = true;
      ports = [
        22
      ];
      settings = {
        X11Forwarding = false;
      };
      # settings = {
      #   # PasswordAuthentication = true;
      #   AllowUsers = null; # Allows all users by default. Can be [ "user1" "user2" ]
      #   UseDns = true;
      #   X11Forwarding = false;
      #   # PermitRootLogin = "prohibit-password"; # "yes", "without-password", "prohibit-password", "forced-commands-only", "no"
      # };
    };
  };
}
