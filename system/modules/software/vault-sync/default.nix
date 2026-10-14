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
    ".git"
    "**/.obsidian/workspace.json"
    "**/.obsidian/workspace-mobile.json"
    ".stfolder"
    ".stignore"
    ".stversions"
  ];
  initialIgnores = pkgs.writeText "vault-sync.stignore" (
    lib.concatStringsSep "\n" ignorePatterns + "\n"
  );
  folder = {
    id = "obsidian-root";
    path = root;
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
    enable = lib.mkEnableOption "Syncthing for the Obsidian directory and all its vaults" // {
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
        folders.Obsidian = folder;
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
        # Install exclusions before the first scan, not only through the REST updater.
        if [ ! -e ${lib.escapeShellArg "${root}/.stignore"} ]; then
          install -m 600 ${initialIgnores} ${lib.escapeShellArg "${root}/.stignore"}
        fi
        if [ ! -e ${lib.escapeShellArg "${root}/vault/.git"} ]; then
          ${lib.getExe pkgs.git} -C ${lib.escapeShellArg "${root}/vault"} init --initial-branch=main
        fi
      '';
    };
  };
}
