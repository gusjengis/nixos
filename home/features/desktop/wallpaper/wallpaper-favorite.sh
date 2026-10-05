#!/usr/bin/env bash
# Serialize the local edit with Git sync, then publish without blocking the picker.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: wallpaper-favorite PATH" >&2
  exit 2
fi

exec 9>"${XDG_RUNTIME_DIR:-/tmp}/wallpaper-sync.lock"
flock -w 180 9
wallpaperctl toggle-favorite "$1"
flock -u 9
exec 9>&-
setsid wallpaper-sync >/dev/null 2>&1 < /dev/null &
