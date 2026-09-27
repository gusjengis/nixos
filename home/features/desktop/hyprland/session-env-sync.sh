# Republish the compositor's display variables to the systemd user manager and
# the D-Bus activation environment, then restart the user services that draw
# windows.
#
# The systemd user manager outlives Hyprland: it starts at login and survives
# every compositor restart. Its environment block therefore keeps whatever
# WAYLAND_DISPLAY and HYPRLAND_INSTANCE_SIGNATURE were current when it was first
# populated. After a Hyprland restart those point at a dead socket, so a GUI
# service started from that environment finds no Wayland display, silently falls
# back to X11, and dies on a stale DISPLAY. thunar.service hit exactly this and
# crash-looped on Restart=on-failure.
#
# Run from autostart.lua before any graphical user service is started.

set -euo pipefail

VARS=(
  WAYLAND_DISPLAY
  DISPLAY
  HYPRLAND_INSTANCE_SIGNATURE
  XDG_CURRENT_DESKTOP
  XDG_SESSION_TYPE
  XDG_RUNTIME_DIR
  GTK_THEME
)

# Only pass variables that are actually set; `import-environment` errors on
# names it cannot resolve.
present=()
for name in "${VARS[@]}"; do
  if [[ -n "${!name-}" ]]; then
    present+=("$name")
  fi
done

if [[ ${#present[@]} -eq 0 ]]; then
  echo "session-env-sync: no session variables set, refusing to clobber" >&2
  exit 1
fi

systemctl --user import-environment "${present[@]}"

# Services activated by D-Bus rather than by systemd read this environment
# instead, so it has to be updated as well or Thunar's org.xfce.FileManager
# activation inherits the stale display.
dbus-update-activation-environment --systemd "${present[@]}"

# Restart rather than start: after a compositor restart the unit is usually
# either failed or still bound to the previous display.
for unit in "$@"; do
  systemctl --user reset-failed "$unit" 2>/dev/null || true
  systemctl --user restart --no-block "$unit"
done
