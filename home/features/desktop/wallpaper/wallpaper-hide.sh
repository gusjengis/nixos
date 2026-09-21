#!/usr/bin/env bash
# Toggle a wallpaper's hidden flag, then publish the change.
#
# Called from the picker's Ctrl+D via execDetached, so it must never block on
# the network: the toggle itself is a local atomic write and is what the picker
# reacts to, while the push happens afterwards and is allowed to fail quietly.

set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: wallpaper-hide PATH" >&2
  exit 2
fi

wallpaperctl toggle-hidden "$1"

# Detached so a slow or offline push cannot keep this process alive behind the
# picker, and so repeated presses do not stack up waiting on the sync lock.
setsid wallpaper-sync >/dev/null 2>&1 &
