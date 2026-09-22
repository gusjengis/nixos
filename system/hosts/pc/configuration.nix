{
  ...
}:

{
  imports = [
    ./gopro-camera.nix
    ./windows-vm.nix
  ];

  bedtimeLockout.enable = false;
  nvidia.enable = true;
  virtual-machines.enable = true;
  programs.steam.enable = true;
  system.stateVersion = "25.05";
}
