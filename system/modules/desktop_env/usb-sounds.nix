{
  config,
  lib,
  pkgs,
  ...
}:

let
  # Sounds ripped straight from real Windows installs (Windows/Media) so
  # this matches the stock Windows USB connect/disconnect chime exactly.
  # win10 came from the old sda2 install, win11 from the current nvme0n1p3
  # install (build 26200, 25H2). Both sets are kept in the repo; the
  # edition option below just picks which one actually plays.
  edition = config.usbSounds.edition;
  assets = ./assets + "/${edition}";
  insertWav = "${assets}/Windows Hardware Insert.wav";
  removeWav = "${assets}/Windows Hardware Remove.wav";

  user = "gusjengis";

  playSound = wav:
    pkgs.writeShellApplication {
      name = "usb-sound-play";
      runtimeInputs = [ pkgs.pipewire ];
      text = ''
        exec pw-play "${wav}"
      '';
    };

  # PipeWire only accepts clients that live inside the user's own login
  # cgroup (user@<uid>.service). A plain system unit with User= runs under
  # system.slice and gets rejected, so the udev-triggered system unit just
  # asks the user's own systemd --user instance to run the player; that way
  # the pw-play process is actually spawned by (and lives inside) the user
  # session.
  userServiceName = name: "usb-sound-play-${name}.service";

  triggerService = name: {
    description = "Trigger USB ${name} sound in user session";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = pkgs.writeShellScript "usb-sound-trigger-${name}" ''
        uid=$(${pkgs.util-linux}/bin/runuser -u ${user} -- ${pkgs.coreutils}/bin/id -u)
        exec ${pkgs.util-linux}/bin/runuser -u ${user} -- env XDG_RUNTIME_DIR="/run/user/$uid" ${pkgs.systemd}/bin/systemctl --user start ${userServiceName name}
      '';
    };
  };

  userPlayService = wav: {
    description = "Play USB sound";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${playSound wav}/bin/usb-sound-play";
    };
  };
in
{
  options.usbSounds.edition = lib.mkOption {
    type = lib.types.enum [
      "win10"
      "win11"
    ];
    default = "win10";
    description = "Which ripped Windows sound set to play on USB connect/disconnect.";
  };

  # Only machines with a DE (hyprland.enable) have a user session worth
  # chiming at; headless/server hosts skip this entirely.
  config = lib.mkIf config.hyprland.enable {
    # TAG+="systemd"/ENV{SYSTEMD_WANTS} only reliably starts units on
    # add/change events; systemd does not process it the same way for a
    # "remove" event (the device unit is being torn down, not appearing), so
    # RUN+= with `systemctl --no-block start` is used for both directions.
    services.udev.extraRules = ''
      ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", RUN+="${pkgs.systemd}/bin/systemctl --no-block start usb-sound-connect.service"
      ACTION=="remove", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", RUN+="${pkgs.systemd}/bin/systemctl --no-block start usb-sound-disconnect.service"
    '';

    systemd.services.usb-sound-connect = triggerService "connect";
    systemd.services.usb-sound-disconnect = triggerService "disconnect";

    systemd.user.services.usb-sound-play-connect = userPlayService insertWav;
    systemd.user.services.usb-sound-play-disconnect = userPlayService removeWav;
  };
}
