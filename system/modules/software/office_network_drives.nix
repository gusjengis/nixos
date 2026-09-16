{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.officeNetworkDrives;
  credentialsFile = "/home/gusjengis/.config/secrets/office-smb-credentials";
  mountOptions = [
    "credentials=${credentialsFile}"
    "uid=1000"
    "gid=100"
    "file_mode=0664"
    "dir_mode=0775"
    "vers=3.0"
    "noperm"
    "rw"
    "_netdev"
    "nofail"
    "noauto"
    "x-systemd.automount"
    "x-systemd.idle-timeout=300"
    "x-systemd.mount-timeout=10s"
  ];
in
{
  options.officeNetworkDrives = {
    enable = lib.mkEnableOption "Azure Green office network drives" // {
      default = true;
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = with pkgs; [
      cifs-utils
      samba
    ];

    boot.supportedFilesystems = [ "cifs" ];

    services.samba.settings.global = {
      workgroup = "AZUREGREEN";
      "client min protocol" = "SMB2";
      "client max protocol" = "SMB3";
      "name resolve order" = "host bcast";
    };

    environment.etc."samba/smb.conf" = lib.mkIf (!config.services.samba.enable) {
      text = ''
        [global]
          workgroup = AZUREGREEN
          client min protocol = SMB2
          client max protocol = SMB3
          name resolve order = host bcast
      '';
    };

    systemd.tmpfiles.rules = [
      "d /mnt/office 0755 root root -"
      "d /mnt/office/orthos 0755 root root -"
      "d /mnt/office/company 0755 root root -"
    ];

    fileSystems."/mnt/office/orthos" = {
      device = "//10.145.0.15/orthos";
      fsType = "cifs";
      options = mountOptions;
    };

    fileSystems."/mnt/office/company" = {
      device = "//10.145.0.18/company";
      fsType = "cifs";
      options = mountOptions;
    };
  };
}
