# Main desktop.
{ pkgs, inputs, ... }:
{
  laptop.enable = false;

  gaming.enable = true;
  bambu.enable = true;
  windowsVm.enable = true;

  home.packages = [
    inputs.alga.packages.${pkgs.stdenv.hostPlatform.system}.default
    pkgs.easyeffects
    pkgs.arduino
    pkgs.android-studio
  ];
}
