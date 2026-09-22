{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.bedtimeLockout;
  stateDir = "/run/bedtime-lockout";

  wakeSession = pkgs.writeShellScript "bedtime-lockout-wake" ''
    set -eu

    if [ ! -e ${stateDir}/active ]; then
      exit 0
    fi

    if [ -s ${stateDir}/scopes ]; then
      while IFS=' ' read -r scope uid user; do
        ${pkgs.systemd}/bin/systemctl thaw "$scope" 2>/dev/null || true
        # hyprctl is resolved from the user's own profile rather than from
        # pkgs.hyprland. Hyprland is installed by Home Manager from a personal
        # fork, so referring to nixpkgs here would both build a second, unused
        # Hyprland and risk talking to the compositor over a mismatched IPC.
        ${pkgs.util-linux}/bin/runuser -u "$user" -- \
          ${pkgs.coreutils}/bin/env XDG_RUNTIME_DIR="/run/user/$uid" \
            PATH="/home/$user/.nix-profile/bin:/etc/profiles/per-user/$user/bin" \
            hyprctl dispatch 'hl.dsp.dpms({ action = "on" })' \
            >/dev/null 2>&1 || true
      done < ${stateDir}/scopes
    fi
    # should prevent the macbook trackpad from being frozen after a thaw
    for hid_id in $(ls /sys/bus/hid/drivers/magicmouse/ 2>/dev/null | ${pkgs.gnugrep}/bin/grep '^0019:'); do
      echo -n "$hid_id" | ${pkgs.coreutils}/bin/tee /sys/bus/hid/drivers/magicmouse/unbind >/dev/null 2>&1 || true
      ${pkgs.coreutils}/bin/sleep 0.5
      echo -n "$hid_id" | ${pkgs.coreutils}/bin/tee /sys/bus/hid/drivers/magicmouse/bind >/dev/null 2>&1 || true
    done

    if [ -s ${stateDir}/audio ]; then
      while IFS=' ' read -r uid user was_muted; do
        if [ "$was_muted" = 0 ]; then
          ${pkgs.util-linux}/bin/runuser -u "$user" -- \
            ${pkgs.coreutils}/bin/env XDG_RUNTIME_DIR="/run/user/$uid" \
              ${pkgs.wireplumber}/bin/wpctl set-mute @DEFAULT_AUDIO_SINK@ 0 \
              >/dev/null 2>&1 || true
        fi
      done < ${stateDir}/audio
    fi

    ${pkgs.coreutils}/bin/rm -rf ${stateDir}
  '';

  wakeWatcher = pkgs.writeText "bedtime-input-wake.py" ''
    import fcntl
    import glob
    import os
    import select
    import struct
    import subprocess
    import time

    EVIOCGRAB = 0x40044590
    EV_SYN = 0
    EV_KEY = 1
    EV_REL = 2
    EV_ABS = 3
    EVENT = struct.Struct("llHHi")
    READY = "${stateDir}/watcher-ready"

    devices = {}

    def physical_device(path):
        event = os.path.basename(path)
        sys_path = os.path.realpath(f"/sys/class/input/{event}/device")
        if "/devices/virtual/input/" in sys_path:
            return False
        try:
            with open(f"/sys/class/input/{event}/device/name", encoding="utf-8") as name_file:
                name = name_file.read().strip()
        except OSError:
            return False
        return name not in {"Power Button", "Sleep Button"}

    def scan():
        current = set(glob.glob("/dev/input/event*"))
        for path in list(devices):
            if path not in current:
                os.close(devices.pop(path))
        for path in current - devices.keys():
            if not physical_device(path):
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                fcntl.ioctl(fd, EVIOCGRAB, 1)
                devices[path] = fd
            except OSError:
                try:
                    os.close(fd)
                except (OSError, UnboundLocalError):
                    pass

    scan()
    os.makedirs("${stateDir}", exist_ok=True)
    open(READY, "w", encoding="utf-8").close()

    while os.path.exists("${stateDir}/active"):
        scan()
        readable, _, _ = select.select(list(devices.values()), [], [], 1.0)
        wake = False
        for fd in readable:
            try:
                data = os.read(fd, EVENT.size * 64)
            except OSError:
                continue
            for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, event_type, _, value = EVENT.unpack_from(data, offset)
                if event_type == EV_KEY and value == 1:
                    wake = True
                elif event_type in (EV_REL, EV_ABS) and value != 0:
                    wake = True
            if wake:
                break
        if wake:
            subprocess.run(
                ["${pkgs.systemd}/bin/systemctl", "start", "bedtime-lockout-wake.service"],
                check=False,
            )
            break

    for fd in devices.values():
        try:
            fcntl.ioctl(fd, EVIOCGRAB, 0)
            os.close(fd)
        except OSError:
            pass
  '';

  control = pkgs.writeShellScript "bedtime-lockout-control" ''
    set -eu

    action="''${1:-reconcile}"
    hour="$(${pkgs.coreutils}/bin/date +%H)"
    blocked=false
    if [ "$hour" -ge ${toString cfg.startHour} ] || [ "$hour" -lt ${toString cfg.endHour} ]; then
      blocked=true
    fi

    inhibit_device() {
      device="$1"
      [ -w "$device/inhibited" ] || return 0
      name="$(${pkgs.coreutils}/bin/cat "$device/name" 2>/dev/null || true)"
      case "$name" in
        "Power Button"|"Sleep Button") return 0 ;;
      esac
      printf '1' > "$device/inhibited"
    }

    inhibit_all() {
      for device in /sys/class/input/input*; do
        inhibit_device "$device"
      done
    }

    uninhibit_all() {
      for inhibited in /sys/class/input/input*/inhibited; do
        [ -w "$inhibited" ] && printf '0' > "$inhibited"
      done
    }

    if [ "$action" = hotplug ]; then
      if $blocked; then
        inhibit_device "/sys''${DEVPATH:-}"
      fi
      exit 0
    fi

    if $blocked; then
      ${pkgs.systemd}/bin/systemctl stop bedtime-input-wake.service 2>/dev/null || true
      ${pkgs.coreutils}/bin/mkdir -p ${stateDir}
      ${pkgs.coreutils}/bin/rm -f ${stateDir}/watcher-ready

      if [ ! -e ${stateDir}/active ]; then
        : > ${stateDir}/scopes
        : > ${stateDir}/audio
        : > ${stateDir}/active
      fi

      ${pkgs.systemd}/bin/loginctl list-sessions --no-legend | while read -r session _; do
          uid="$(${pkgs.systemd}/bin/loginctl show-session "$session" -P User 2>/dev/null || true)"
          user="$(${pkgs.systemd}/bin/loginctl show-session "$session" -P Name 2>/dev/null || true)"
          seat="$(${pkgs.systemd}/bin/loginctl show-session "$session" -P Seat 2>/dev/null || true)"
          remote="$(${pkgs.systemd}/bin/loginctl show-session "$session" -P Remote 2>/dev/null || true)"
          type="$(${pkgs.systemd}/bin/loginctl show-session "$session" -P Type 2>/dev/null || true)"
          scope="$(${pkgs.systemd}/bin/loginctl show-session "$session" -P Scope 2>/dev/null || true)"

          if [ "$seat" != seat0 ] || [ "$remote" != no ] || [ -z "$scope" ]; then
            continue
          fi
          case "$type" in
            wayland|x11) ;;
            *) continue ;;
          esac
          if ${pkgs.gnugrep}/bin/grep -q "^$scope " ${stateDir}/scopes; then
            continue
          fi

          # Pause cooperative players and mute output before freezing applications.
          ${pkgs.coreutils}/bin/timeout 5 ${pkgs.util-linux}/bin/runuser -u "$user" -- \
            ${pkgs.coreutils}/bin/env XDG_RUNTIME_DIR="/run/user/$uid" \
              DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$uid/bus" \
              ${pkgs.playerctl}/bin/playerctl --all-players --no-messages pause \
              >/dev/null 2>&1 || true

          was_muted=0
          if ${pkgs.coreutils}/bin/timeout 5 ${pkgs.util-linux}/bin/runuser -u "$user" -- \
            ${pkgs.coreutils}/bin/env XDG_RUNTIME_DIR="/run/user/$uid" \
              ${pkgs.wireplumber}/bin/wpctl get-volume @DEFAULT_AUDIO_SINK@ 2>/dev/null \
              | ${pkgs.gnugrep}/bin/grep -q MUTED; then
            was_muted=1
          fi
          printf '%s %s %s\n' "$uid" "$user" "$was_muted" >> ${stateDir}/audio
          ${pkgs.util-linux}/bin/runuser -u "$user" -- \
            ${pkgs.coreutils}/bin/env XDG_RUNTIME_DIR="/run/user/$uid" \
              ${pkgs.wireplumber}/bin/wpctl set-mute @DEFAULT_AUDIO_SINK@ 1 \
              >/dev/null 2>&1 || true

          # See the note on the matching dpms-on call above.
          ${pkgs.util-linux}/bin/runuser -u "$user" -- \
            ${pkgs.coreutils}/bin/env XDG_RUNTIME_DIR="/run/user/$uid" \
              PATH="/home/$user/.nix-profile/bin:/etc/profiles/per-user/$user/bin" \
              hyprctl dispatch 'hl.dsp.dpms({ action = "off" })' \
              >/dev/null 2>&1 || true

          printf '%s %s %s\n' "$scope" "$uid" "$user" >> ${stateDir}/scopes
          ${pkgs.systemd}/bin/systemctl freeze "$scope"
      done

      inhibit_all
      exit 0
    fi

    if [ -e ${stateDir}/active ]; then
      ${pkgs.systemd}/bin/systemctl start --no-block bedtime-input-wake.service
      count=0
      while [ ! -e ${stateDir}/watcher-ready ] && [ "$count" -lt 50 ]; do
        ${pkgs.coreutils}/bin/sleep 0.1
        count=$((count + 1))
      done
    fi
    uninhibit_all
  '';
in
{
  options.bedtimeLockout = {
    enable = lib.mkEnableOption "scheduled local input and graphical session lockout";
    startHour = lib.mkOption {
      type = lib.types.ints.between 0 23;
      default = 21;
    };
    endHour = lib.mkOption {
      type = lib.types.ints.between 0 23;
      default = 1;
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.bedtime-lockout = {
      description = "Reconcile scheduled bedtime lockout";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = control;
      };
    };

    systemd.services.bedtime-input-wake = {
      description = "Wake frozen desktop on first physical input after bedtime";
      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.python3}/bin/python ${wakeWatcher}";
        Restart = "on-failure";
        RestartSec = 1;
      };
    };

    systemd.services.bedtime-lockout-wake = {
      description = "Thaw desktop after bedtime input";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = wakeSession;
      };
    };

    systemd.timers.bedtime-lockout = {
      description = "Check bedtime lockout state each minute";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnBootSec = "30s";
        OnCalendar = "*-*-* *:*:00";
        AccuracySec = "1s";
        Unit = "bedtime-lockout.service";
      };
    };

    services.udev.extraRules = ''
      ACTION=="add", SUBSYSTEM=="input", RUN+="${control} hotplug"
    '';
  };
}
