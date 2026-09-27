{ config, lib, pkgs, ... }:

let
  script = pkgs.writeShellApplication {
    name = "supernote-mirror";
    runtimeInputs = [ pkgs.android-tools pkgs.coreutils pkgs.curl pkgs.gnugrep pkgs.gawk pkgs.libnotify pkgs.chromium ];
    text = builtins.readFile ./supernote-mirror.sh;
  };
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ script ];

    systemd.user.services.supernote-mirror = {
      Unit = {
        Description = "Supernote screen mirror tunnel";
        After = [ "graphical-session.target" ];
        PartOf = [ "graphical-session.target" ];
      };
      Service = {
        Type = "simple";
        ExecStart = "${script}/bin/supernote-mirror run";
        ExecStop = "${script}/bin/supernote-mirror stop";
        Restart = "no";
      };
    };

  };
}
