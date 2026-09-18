{
  config,
  pkgs,
  lib,
  ...
}:

let
  sharedKeyPath = "${toString ./../../keys/shared_ed25519.pub}";
in
{
  imports = [
    ./hardware-configuration.nix
    ./data_drive_server.nix
    ./immich.nix
    ./nextcloud.nix
    ./parakeet_asr.nix
    ./ultrabridge.nix
  ];

  hyprland.enable = false;
  vial.enable = false;

  # this machine hosts the shared /data drive for the tailnet
  dataDrive.client.enable = false;
  nextcloud.enable = true;
  nextcloud.funnel.enable = true;
  immich.enable = true;
  immich.funnel.enable = true;
  ultrabridge.enable = true;
  ultrabridge.funnel.enable = true;

  parakeetAsr.enable = true;
  bedtimeLockout.enable = true;

  # legacy nvidia driver for GTX 1080
  services.xserver.videoDrivers = [ "nvidia" ];

  hardware = {
    nvidia = {
      modesetting.enable = true;
      package = config.boot.kernelPackages.nvidiaPackages.legacy_580;
      open = false;
    };

    graphics = {
      enable = true;
      enable32Bit = true;
    };
  };

  boot.supportedFilesystems = [ "btrfs" ];

  fileSystems."/data" = {
    device = "/dev/disk/by-label/data";
    fsType = "btrfs";
    options = [
      "compress=zstd"
      "noatime"
      "nofail"
    ];
  };

  services.btrfs.autoScrub = {
    enable = true;
    interval = "monthly";
    fileSystems = [ "/data" ];
  };

  services.udev.extraRules = ''
    ENV{ID_FS_UUID}=="756c06b0-13e0-41b3-848f-03e6b2df755d", ENV{UDISKS_IGNORE}="1"
  '';

  # User for Dad
  users.users.trevogre = {
    isNormalUser = true;
    description = "Trevor Green";
    extraGroups = [
      "networkmanager"
      "wheel"
      "dialout"
      "docker"
    ];
    packages = with pkgs; [ home-manager ];
    openssh.authorizedKeys.keys = lib.optionals (builtins.pathExists sharedKeyPath) [
      (lib.strings.removeSuffix "\n" (builtins.readFile sharedKeyPath))
    ];

  };

  system.stateVersion = "25.11";
}
