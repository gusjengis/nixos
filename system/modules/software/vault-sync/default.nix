{
  config,
  lib,
  pkgs,
  hostName,
  ...
}:
let
  cfg = config.vaultSync;
  home = config.users.users.${cfg.user}.home;
  root = "${home}/Documents/Obsidian";
  peers = lib.removeAttrs cfg.deviceIds [ hostName ];
  ignorePatterns = [
    "/.git"
    "/.obsidian/workspace.json"
    "/.obsidian/workspace-mobile.json"
  ];
  initialIgnores = pkgs.writeText "vault-sync.stignore" (
    lib.concatStringsSep "\n" ignorePatterns + "\n"
  );
  folder = name: {
    id = "obsidian-${lib.toLower name}";
    path = "${root}/${name}";
    devices = builtins.attrNames peers;
    type = "sendreceive";
    inherit ignorePatterns;
    versioning = lib.mkIf (hostName == "omega") {
      type = "staggered";
      params.maxAge = "2592000";
    };
  };
in
{
  options.vaultSync = {
    enable = lib.mkEnableOption "Syncthing for the Notes and manual writing vaults" // {
      default = builtins.hasAttr hostName cfg.deviceIds;
    };
    user = lib.mkOption {
      type = lib.types.str;
      default = "gusjengis";
      description = "Owner of the vaults and Syncthing daemon.";
    };
    deviceIds = lib.mkOption {
      type = lib.types.attrsOf lib.types.str;
      default = import ./devices.nix;
      description = "Host names mapped to public Syncthing device IDs; private identities stay on each host.";
    };
    identityDirectory = lib.mkOption {
      type = lib.types.str;
      default = "${home}/.config/syncthing";
      description = "Runtime directory containing this host's cert.pem and key.pem.";
    };
    notes.enable =
      lib.mkEnableOption "syncing the existing Notes vault after Obsidian Sync is stopped"
      // {
        default = true;
      };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = config.tailscale.enable && builtins.hasAttr hostName cfg.deviceIds;
        message = "vaultSync requires Tailscale and a device ID for ${hostName}.";
      }
    ];
    services.syncthing = {
      enable = true;
      user = cfg.user;
      group = "users";
      dataDir = "${home}/.local/share/syncthing";
      configDir = cfg.identityDirectory;
      guiAddress = "127.0.0.1:8384";
      openDefaultPorts = false;
      overrideDevices = true;
      overrideFolders = true;
      settings = {
        devices = lib.mapAttrs (name: id: {
          inherit id;
          addresses = [ "tcp://${name}:22000" ];
        }) peers;
        folders = {
          vault = folder "vault";
        }
        // lib.optionalAttrs cfg.notes.enable { Notes = folder "Notes"; };
        options = {
          listenAddresses = [ "tcp://0.0.0.0:22000" ];
          globalAnnounceEnabled = false;
          localAnnounceEnabled = false;
          relaysEnabled = false;
          natEnabled = false;
          urAccepted = -1;
        };
      };
    };
    networking.firewall.interfaces.tailscale0.allowedTCPPorts = [ 22000 ];
    systemd.services.syncthing = {
      after = [ "tailscaled.service" ];
      wants = [ "tailscaled.service" ];
      unitConfig.ConditionPathExists = [
        "${cfg.identityDirectory}/cert.pem"
        "${cfg.identityDirectory}/key.pem"
      ];
      serviceConfig.UMask = "0077";
      preStart = ''
        mkdir -p ${lib.escapeShellArg "${root}/vault"}
        ${lib.optionalString cfg.notes.enable "mkdir -p ${lib.escapeShellArg "${root}/Notes"}"}
        # Install exclusions before the first scan, not only through the REST updater.
        for folder in ${lib.escapeShellArg "${root}/vault"} ${lib.optionalString cfg.notes.enable (lib.escapeShellArg "${root}/Notes")}; do
          if [ ! -e "$folder/.stignore" ]; then
            install -m 600 ${initialIgnores} "$folder/.stignore"
          fi
        done
        if [ ! -e ${lib.escapeShellArg "${root}/vault/.git"} ]; then
          ${lib.getExe pkgs.git} -C ${lib.escapeShellArg "${root}/vault"} init --initial-branch=main
        fi
      '';
    };
  };
}
