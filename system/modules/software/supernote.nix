{
  config,
  lib,
  pkgs,
  ...
}:

{
  options.supernote.enable = lib.mkEnableOption "Supernote ADB access";

  config = lib.mkIf config.supernote.enable {
    environment.systemPackages = [ pkgs.android-tools ];

    services.udev.extraRules = ''
      ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="2207", ATTR{idProduct}=="0017", TAG+="systemd", ENV{SYSTEMD_WANTS}+="supernote-connect.service"
      ACTION=="remove", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ENV{ID_VENDOR_ID}=="2207", TAG+="systemd", ENV{SYSTEMD_WANTS}+="supernote-disconnect.service"
    '';

    systemd.services.supernote-connect = {
      description = "Start Supernote user tunnel on USB connect";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = pkgs.writeShellScript "supernote-connect" ''
          uid=$(${pkgs.coreutils}/bin/id -u gusjengis)
          exec ${pkgs.util-linux}/bin/runuser -u gusjengis -- env XDG_RUNTIME_DIR="/run/user/$uid" ${pkgs.systemd}/bin/systemctl --user start supernote-mirror.service
        '';
      };
    };

    systemd.services.supernote-disconnect = {
      description = "Stop Supernote user tunnel on USB disconnect";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = pkgs.writeShellScript "supernote-disconnect" ''
          uid=$(${pkgs.coreutils}/bin/id -u gusjengis)
          exec ${pkgs.util-linux}/bin/runuser -u gusjengis -- env XDG_RUNTIME_DIR="/run/user/$uid" ${pkgs.systemd}/bin/systemctl --user stop supernote-mirror.service
        '';
      };
    };
  };
}
