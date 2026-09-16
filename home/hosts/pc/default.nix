# Main desktop.
{ pkgs, inputs, ... }:
{
  laptop.enable = false;

  gaming.enable = true;
  gameDev.enable = true;
  bambu.enable = true;
  windowsVm.enable = true;

  # Machine-specific packages. These were in the untracked local.nix.
  home.packages = [
    inputs.alga.packages.${pkgs.stdenv.hostPlatform.system}.default
    pkgs.easyeffects
  ];
}
