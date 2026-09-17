{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

{
  imports = [
    ./hardware-configuration.nix
    ./asahi.nix
    ./office_network_gateway.nix
  ];

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];
  boot.loader.efi.canTouchEfiVariables = false;
  networking.networkmanager.wifi.backend = "iwd";

  hardware.graphics = {
    enable = true;
    package = pkgs.mesa;
    extraPackages = with pkgs; [
      libgbm
      libglvnd
    ];
  };

  hardware.asahi.enable = true;

  environment.systemPackages = with pkgs; [
    iwd
  ];
  services.keyd = {
    enable = true;

    keyboards = {
      default = {
        extraConfig = "          \t[ids]\n          \t\t05ac:0353:6f083222\n\t\t[main]\n\t\t\tcapslock = overload(control, esc)        ";
      };
    };
  };

  networking.networkmanager.wifi.powersave = false;
  system.stateVersion = "25.11"; # DO NOT CHANGE
}
