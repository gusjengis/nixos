#!/usr/bin/env bash
# Ask geoclue where this machine is and record it for wallpaperctl.
#
# wallpaperctl picks wallpapers by the sun's elevation, so it needs a
# latitude and longitude. The result is kept in location.json and only ever
# replaced by a fresh fix: a failed lookup (offline, geoclue slow to answer)
# leaves the last good position in place, and with no file at all wallpaperctl
# falls back to the coordinate Nix baked into its wrapper.
#
# where-am-i is geoclue's own demo client. It prints a block like
#   Latitude:    47.252900°
#   Longitude:   -122.444000°
#   Accuracy:    25000 meters
# and keeps running until the timeout, so the first block is taken.

set -euo pipefail

state="${XDG_STATE_HOME:-$HOME/.local/state}/wallpaper"
target="$state/location.json"

# Accuracy level 4 is "city", which is all the sun needs and lets geoclue
# answer from the cheapest source.
output="$(timeout 60 where-am-i --timeout 45 --accuracy-level 4 2>&1 || true)"

latitude="$(sed -n 's/^Latitude: *\(-\{0,1\}[0-9.]*\).*/\1/p' <<<"$output" | head -n 1)"
longitude="$(sed -n 's/^Longitude: *\(-\{0,1\}[0-9.]*\).*/\1/p' <<<"$output" | head -n 1)"
accuracy="$(sed -n 's/^Accuracy: *\([0-9.]*\).*/\1/p' <<<"$output" | head -n 1)"

if [ -z "$latitude" ] || [ -z "$longitude" ]; then
  echo "wallpaper-locate: no fix from geoclue, keeping the previous location" >&2
  printf '%s\n' "$output" | tail -n 5 >&2
  exit 0
fi

mkdir -p "$state"
printf '{"latitude":%s,"longitude":%s,"accuracy":%s,"at":"%s"}\n' \
  "$latitude" "$longitude" "${accuracy:-null}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$target.tmp"
mv "$target.tmp" "$target"
echo "wallpaper-locate: $latitude, $longitude (±${accuracy:-?} m)"
