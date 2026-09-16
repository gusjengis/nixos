#!/usr/bin/env bash
set -euo pipefail

desktop_name="${1:?usage: launch-desktop-entry.sh <desktop-id>}"
desktop_name="${desktop_name%.desktop}"
desktop_id="${desktop_name}.desktop"

desktop_path="$HOME/.local/share/applications/$desktop_id"
if [[ ! -f "$desktop_path" ]]; then
    repo_root="${NIXOS_CONFIG_ROOT:-/etc/nixos}"
    desktop_path="$repo_root/home/features/desktop/webapps/applications/$desktop_id"
fi

if command -v gtk-launch >/dev/null 2>&1; then
    exec gtk-launch "$desktop_name"
fi

if command -v gio >/dev/null 2>&1; then
    exec gio launch "$desktop_path"
fi

exec_line=''
while IFS= read -r line; do
    if [[ "$line" == Exec=* ]]; then
        exec_line="${line#Exec=}"
        break
    fi
done < "$desktop_path"

if [[ -n "$exec_line" ]]; then
    exec_line="${exec_line//%[fFuUdDnNickvm]/}"
    eval "exec $exec_line"
fi

printf 'Could not launch %s: no launcher backend or Exec line is available.\n' "$desktop_id" >&2
exit 127
