{ pkgs, ... }:

{
  home.packages = with pkgs; [
    btop
    nethogs
    nvtopPackages.full
  ];
}
