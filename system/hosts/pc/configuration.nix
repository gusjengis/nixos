{
  pkgs,
  ...
}:

{
  imports = [
    ./windows-vm.nix
  ];

  bedtimeLockout.enable = false;
  # Vial keyboard only ever gets plugged into this machine.
  vial.enable = true;
  networking.networkmanager.wifi.backend = "iwd";
  networking.networkmanager.wifi.powersave = false;
  networking.wireless.iwd.settings.Settings.AutoConnect = true;
  systemd.services.NetworkManager = {
    after = [ "iwd.service" ];
    requires = [ "iwd.service" ];
  };
  nvidia.enable = true;
  virtual-machines.enable = true;
  programs.steam.enable = true;
  boot.loader.efi.efiSysMountPoint = "/boot/efi";
  system.stateVersion = "25.05";

  environment.systemPackages = [ pkgs.iwd ];
}
