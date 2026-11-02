# Main desktop.
{ pkgs, ... }:
{
  laptop.enable = false;

  gaming.enable = true;
  bambu.enable = true;
  windowsVm.enable = true;
  mediaEditing.enable = true;

  home.packages = [
    pkgs.easyeffects
    pkgs.arduino
    pkgs.android-studio
  ];
}
