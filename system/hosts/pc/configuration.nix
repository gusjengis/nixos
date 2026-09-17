{
  ...
}:

{
  imports = [ ./windows-vm.nix ];

  nvidia.enable = true;
  virtual-machines.enable = true;
  programs.steam.enable = true;
  system.stateVersion = "25.05";
}
