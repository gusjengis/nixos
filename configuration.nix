{
  config,
  lib,
  inputs,
  pkgs,
  stable,
  ...
}:
{
  # VM stuff for testing AUR packages
  virtualisation.libvirtd.enable = true;
  programs.virt-manager.enable = true;

  environment.systemPackages = with pkgs; [
    qemu_kvm
    virt-manager
    virt-viewer
    libvirt
    OVMF
    spice-gtk
  ];

  users.users.gusjengis.extraGroups = [
    "libvirtd"
    "kvm"
  ];

  system.stateVersion = "25.05";
}
