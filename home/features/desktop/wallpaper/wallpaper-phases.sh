#!/usr/bin/env bash
# Correct a wallpaper's time-of-day phases, then publish the change.
#
# Ctrl+T in the picker. Same shape as wallpaper-hide: the local write is what
# the picker reacts to, and the push runs detached so it can never hold up the
# UI or fail loudly when offline.

set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: wallpaper-phases PATH PHASE[,PHASE...]|reset" >&2
  exit 2
fi

wallpaperctl set-phases "$1" "$2"

setsid wallpaper-sync >/dev/null 2>&1 &
