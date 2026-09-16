{ pkgs, ... }:

{
  home.packages = with pkgs; [
    thunar
    tumbler
    thunar-volman
    thunar-archive-plugin
    file-roller
    gvfs
    udiskie
  ];

  systemd.user.services.thunar = {
    Unit.Description = "Thunar file manager daemon";

    Service = {
      Type = "dbus";
      ExecStart = "${pkgs.thunar}/bin/Thunar --daemon";
      BusName = "org.xfce.FileManager";
      KillMode = "process";
      Restart = "on-failure";
      RestartSec = 2;
    };
  };
}
