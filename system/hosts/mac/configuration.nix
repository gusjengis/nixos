{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

let
  asahiFirmware = pkgs.requireFile {
    name = "firmware.cpio";
    hash = "sha256-GZ/dZgjZHgRxGf9XJjXX/JFVcRYN/+Z+FcwrEkvsH2A=";
    message = ''
      Seed this Mac's Asahi firmware before building:
        nix-store --add-fixed sha256 /boot/vendorfw/firmware.cpio
    '';
  };
  asahiFirmwareDirectory = pkgs.runCommandLocal "asahi-peripheral-firmware-source" { } ''
    mkdir -p "$out"
    ln -s ${asahiFirmware} "$out/firmware.cpio"
  '';
in
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
  hardware.asahi.peripheralFirmwareDirectory = asahiFirmwareDirectory;

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
