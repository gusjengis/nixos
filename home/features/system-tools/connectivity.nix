{ config, pkgs, ... }:

{
  home.packages = with pkgs; [
    blueman
    bluez
    # nmgui
  ];
}
