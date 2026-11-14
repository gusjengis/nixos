{
  pkgs,
  inputs,
  ...
}:

let
  # Match Home Manager's app: the privileged browser helper must use its build.
  desktopPkgs = import inputs.nixpkgs {
    system = pkgs.stdenv.hostPlatform.system;
    config.allowUnfree = true;
  };
in
{
  imports = [
    ./windows-vm.nix
    ./windows-reboot
    ./secure-boot.nix
  ];

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
  gpu-unlock.enable = true;
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
  programs.steam.enable = true;
  programs._1password = {
    enable = true;
    package = desktopPkgs._1password-cli;
  };
  programs._1password-gui = {
    enable = true;
    package = desktopPkgs._1password-gui;
    polkitPolicyOwners = [ "gusjengis" ];
  };
  boot.loader.efi.efiSysMountPoint = "/boot/efi";
  system.stateVersion = "25.05";

  environment.systemPackages = [ pkgs.iwd ];
}
