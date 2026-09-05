{ config, lib, ... }:
let
  cfg = config.ogWindowsVm;
in
{
  # Host-specific wiring for the "og" Windows VM: a libvirt domain named win11
  # that owns a dedicated NVMe drive and the GTX 1080 through VFIO. Nothing here
  # starts the VM. It stays off until the OG launcher (home-manager) or virsh
  # starts it, and stays running until Windows is shut down from inside.

  # GTX 1080 graphics and HDMI audio; RTX 3090 remains available to NixOS.
  virtual-machines.vfioPciIds = [
    "10de:1b80"
    "10de:10f0"
  ];

  options.ogWindowsVm = {
    enable = lib.mkEnableOption "og Windows VM host integration" // {
      default = true;
    };

    address = lib.mkOption {
      type = lib.types.str;
      default = "192.168.122.18";
      description = "DHCP-reserved address of the VM on the libvirt default network";
    };

    hostShare.enable = lib.mkEnableOption "SMB share exposing the NixOS host to the VM" // {
      default = true;
    };
  };

  config = lib.mkIf cfg.enable {
    # Reachable from the rest of the tailnet even while the VM is off, so the
    # OG launcher can start the domain over SSH and then connect over RDP.
    tailscale.advertiseRoutes = [ "${cfg.address}/32" ];

    # Guest -> host file sharing. The host does not mount the guest; Thunar gets
    # a gvfs smb:// bookmark instead, so a stopped VM cannot stall the file
    # manager the way a kernel CIFS automount did.
    services.samba = lib.mkIf cfg.hostShare.enable {
      enable = true;
      openFirewall = false;
      nmbd.enable = false;
      winbindd.enable = false;
      settings = {
        global = {
          "server role" = "standalone server";
          "security" = "user";
          "map to guest" = "Never";
          "server min protocol" = "SMB3_00";
          "smb ports" = "445";
          "disable netbios" = "yes";
          "hosts allow" = "127.0.0.1 192.168.122.0/24";
          "hosts deny" = "0.0.0.0/0";
        };
        NixOSRoot = {
          path = "/";
          browseable = "yes";
          "read only" = "no";
          "guest ok" = "no";
          "valid users" = "gusjengis";
          "force user" = "gusjengis";
          "force group" = "users";
          "create mask" = "0644";
          "directory mask" = "0755";
        };
      };
    };

    networking.firewall.interfaces.virbr0.allowedTCPPorts = lib.mkIf cfg.hostShare.enable [ 445 ];
  };
}
