{ inputs, lib, pkgs, ... }:
{
  # Resizing is deferred. The 512 MiB ESP fits today's shared initrd, but a
  # future kernel/driver update may need a larger ESP for atomic replacement.
  imports = [ inputs.lanzaboote.nixosModules.lanzaboote ];

  # Only this host moves off GRUB. Plymouth remains independent of the loader.
  grub.enable = false;
  boot.loader = {
    efi.canTouchEfiVariables = true;
    systemd-boot.enable = lib.mkForce false;
    timeout = 0;
  };
  boot.lanzaboote = {
    enable = true;
    pkiBundle = "/var/lib/sbctl";
    configurationLimit = 1;
    settings = {
      editor = false;
      auto-entries = false;
      auto-firmware = false;
      beep = false;
    };
  };

  # Suppress systemd's EFI stub status output; keep the existing Darwin splash.
  boot.kernelParams = [ "rd.systemd.show_status=false" "systemd.show_status=false" ];
  environment.systemPackages = [ pkgs.sbctl pkgs.efibootmgr ];
}
