{ pkgs, ... }:

{
  home.packages = with pkgs; [
    wget
    bat
  ];
}
