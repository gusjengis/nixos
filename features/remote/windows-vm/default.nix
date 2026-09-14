{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.windowsVm;
  windowsIcon = pkgs.runCommand "windows-logo.png" { nativeBuildInputs = [ pkgs.imagemagick ]; } ''
    magick ${./windows-logo.webp} -resize 256x256 $out
  '';

  rdpArgs =
    {
      address,
      user,
      domain,
    }:
    [
      "/v:${address}"
      "/u:${user}"
    ]
    ++ lib.optional (domain != "") "/d:${domain}"
    ++ [
      "/cert:tofu"
      "/sec:nla"
      "/auth-pkg-list:!kerberos,ntlm,!u2u"
      "/network:auto"
      "/gfx"
      "/dynamic-resolution"
      "/clipboard"
      "/sound:sys:pulse"
    ];

  # Reads the password out of a `key=value` credentials file, then hands every
  # argument to xfreerdp through a file descriptor so the password never shows
  # up in the process list.
  mkRdpLauncher =
    {
      name,
      title,
      address,
      user,
      domain,
      credentialsFile,
      extraRuntimeInputs ? [ ],
      prelude ? "",
    }:
    pkgs.writeShellApplication {
      inherit name;
      runtimeInputs = [
        pkgs.freerdp
        pkgs.libnotify
      ]
      ++ extraRuntimeInputs;
      text = ''
        set -eu

        fail() {
          notify-send ${lib.escapeShellArg title} "$1"
          exit 1
        }

        [ -r ${lib.escapeShellArg credentialsFile} ] || fail "Credentials file is missing"

        password=
        while IFS='=' read -r key value; do
          if [ "$key" = password ]; then
            password="$value"
          fi
        done < ${lib.escapeShellArg credentialsFile}

        [ -n "$password" ] || fail "Password is missing from credentials file"

        ${prelude}

        exec 3< <(
          printf '%s\n' ${
            lib.escapeShellArgs (rdpArgs {
              inherit address user domain;
            })
          }
          printf '/p:%s\n' "$password"
        )
        unset password
        exec ${lib.getExe' pkgs.freerdp "xfreerdp"} /args-from:fd:3
      '';
    };

  windowsRdp = mkRdpLauncher {
    name = "windows-rdp";
    title = "Windows RDP";
    inherit (cfg)
      address
      user
      domain
      credentialsFile
      ;
  };

  # The OG VM is not running by default. Start it first, locally through virsh
  # when this machine hosts the domain, otherwise by asking the host over SSH,
  # then wait for Windows to answer on the RDP port before connecting.
  ogRdp = mkRdpLauncher {
    name = "og-rdp";
    title = "OG";
    inherit (cfg.og)
      address
      user
      domain
      credentialsFile
      ;
    extraRuntimeInputs = [
      pkgs.netcat-openbsd
      pkgs.openssh
    ];
    prelude = ''
      vm_name=${lib.escapeShellArg cfg.og.vmName}

      remote_start_command="virsh --connect qemu:///system domstate $vm_name | grep -qx running || virsh --connect qemu:///system start $vm_name"

      start_vm() {
        local state
        if [ -S /run/libvirt/libvirt-sock ] && command -v virsh >/dev/null 2>&1; then
          state="$(virsh --connect qemu:///system domstate "$vm_name" 2>/dev/null || true)"
          if [ "$state" = running ]; then
            return 0
          fi
          notify-send "OG" "Starting the OG virtual machine"
          virsh --connect qemu:///system start "$vm_name" >/dev/null \
            || fail "Could not start $vm_name on this machine"
        else
          notify-send "OG" "Asking ${cfg.og.startHost} to start the OG virtual machine"
          ssh -o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new \
            ${lib.escapeShellArg cfg.og.startHost} \
            "$remote_start_command" >/dev/null \
            || fail "Could not start $vm_name on ${cfg.og.startHost}"
        fi
      }

      wait_for_rdp() {
        local waited=0
        while ! nc -z -w 2 ${lib.escapeShellArg cfg.og.address} 3389 >/dev/null 2>&1; do
          waited=$((waited + 3))
          if [ "$waited" -ge ${toString cfg.og.bootTimeout} ]; then
            fail "OG did not answer on RDP within ${toString cfg.og.bootTimeout} seconds"
          fi
          sleep 3
        done
      }

      start_vm
      wait_for_rdp

      # publish the OG smb:// bookmark now instead of waiting for the next
      # background refresh
      if command -v tailnet-thunar-bookmarks >/dev/null 2>&1; then
        tailnet-thunar-bookmarks refresh >/dev/null 2>&1 || true
      fi
    '';
  };

  launchers = [ windowsRdp ] ++ lib.optional cfg.og.enable ogRdp;
in
{
  options.windowsVm = {
    enable = lib.mkEnableOption "RDP launcher for the Windows VM" // {
      default = true;
    };
    user = lib.mkOption {
      type = lib.types.str;
      default = "Anthony";
      description = "Windows RDP username";
    };
    domain = lib.mkOption {
      type = lib.types.str;
      default = "AZUREGREEN";
      description = "Windows RDP domain";
    };
    address = lib.mkOption {
      type = lib.types.str;
      default = "trevornomad.tail29bd65.ts.net";
      description = "Tailnet hostname of the Windows computer";
    };
    credentialsFile = lib.mkOption {
      type = lib.types.str;
      default = "${config.home.homeDirectory}/.config/secrets/trevornomad-credentials";
      description = "RDP credential file";
    };

    og = {
      enable = lib.mkEnableOption "on-demand launcher for the OG Windows VM" // {
        default = true;
      };
      vmName = lib.mkOption {
        type = lib.types.str;
        default = "win11";
        description = "libvirt domain name of the OG VM";
      };
      startHost = lib.mkOption {
        type = lib.types.str;
        default = "gusjengis@pc.tail29bd65.ts.net";
        description = "SSH target that hosts the OG VM, used from other machines";
      };
      address = lib.mkOption {
        type = lib.types.str;
        default = "192.168.122.18";
        description = "Address of the OG VM, reachable through the advertised tailnet route";
      };
      user = lib.mkOption {
        type = lib.types.str;
        default = "antho";
        description = "OG RDP username";
      };
      domain = lib.mkOption {
        type = lib.types.str;
        default = "";
        description = "OG RDP domain; empty means a local Windows account";
      };
      credentialsFile = lib.mkOption {
        type = lib.types.str;
        default = "${config.home.homeDirectory}/.config/secrets/windows-smb-credentials";
        description = "Credential file holding the OG password";
      };
      smbShare = lib.mkOption {
        type = lib.types.str;
        default = "WindowsRoot";
        description = "SMB share published as the OG Thunar bookmark";
      };
      bootTimeout = lib.mkOption {
        type = lib.types.int;
        default = 180;
        description = "Seconds to wait for the OG VM to answer on RDP";
      };
    };
  };

  config = lib.mkIf (cfg.enable && config.desktopEnv.enable) {
    home.packages = [ pkgs.freerdp ] ++ launchers;

    xdg.dataFile."icons/hicolor/256x256/apps/windows-logo.png".source = windowsIcon;

    xdg.dataFile."applications/windows-vm.desktop".text = ''
      [Desktop Entry]
      Type=Application
      Name=Windows 11
      Comment=Connect to TrevorNomad over RDP
      Exec=${lib.getExe windowsRdp}
      Icon=windows-logo
      Terminal=false
      Categories=Network;RemoteAccess;
    '';

    xdg.dataFile."applications/og-vm.desktop" = lib.mkIf cfg.og.enable {
      text = ''
        [Desktop Entry]
        Type=Application
        Name=OG
        Comment=Start the OG Windows VM and connect over RDP
        Exec=${lib.getExe ogRdp}
        Icon=windows-logo
        Terminal=false
        Categories=Network;RemoteAccess;
      '';
    };
  };
}
