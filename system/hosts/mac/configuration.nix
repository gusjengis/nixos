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
  grub.enable = true;
  boot.loader = {
    efi.canTouchEfiVariables = false;
    systemd-boot.enable = false;
    grub = {
      configurationLimit = 3;
      efiInstallAsRemovable = true;
      extraPrepareConfig = lib.mkAfter ''
        grubCore="@bootPath@/grub/arm64-efi/core.efi"
        efiFallback="@bootPath@/EFI/BOOT/BOOTAA64.EFI"
        if [ ! -e "$grubCore" ] || ! ${pkgs.diffutils}/bin/cmp -s "$grubCore" "$efiFallback"; then
          ${pkgs.coreutils}/bin/rm -f "@bootPath@/grub/state"
        fi
      '';
    };
  };
  boot.kernelParams = [ "appledrm.show_notch=1" ];
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
