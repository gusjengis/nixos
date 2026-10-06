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
  networking.wireless.iwd.settings.Settings.AutoConnect = false;
  networking.networkmanager.settings."device-wlan0" = {
    "match-device" = "interface-name:wlan0";
    "wifi.iwd.autoconnect" = false;
  };
  systemd.services.NetworkManager = {
    after = [ "iwd.service" ];
    requires = [ "iwd.service" ];
  };
  nvidia.enable = true;
  boot.initrd.kernelModules = [
    "nvidia"
    "nvidia_modeset"
    "nvidia_drm"
  ];
  # NixOS loads nvidia_uvm through a modprobe softdep on nvidia, which never
  # fires when nvidia is loaded in the initrd above. Without it CUDA (and so
  # NVENC in OBS) fails with CUDA_ERROR_UNKNOWN.
  boot.kernelModules = [ "nvidia_uvm" ];
  virtual-machines.enable = true;
  boot.loader.efi.efiSysMountPoint = "/boot/efi";
  system.stateVersion = "25.05";

  environment.systemPackages = [ pkgs.iwd ];
}
