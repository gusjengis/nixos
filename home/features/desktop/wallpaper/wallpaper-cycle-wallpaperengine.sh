#!/usr/bin/env bash
# wallpaper_cycle.sh

if ! command -v linux-wallpaperengine &>/dev/null; then
  exit 1
fi

# Wallpaper IDs
wallpapers=(
  1130661944 # good, asian window, blue sky
  2347484937 # super good, green hillside, red house
  2994110411 # a favorite, field, blue flowers, houses
  3006959414 # good, river, bridge, village, noticing this one spinning up fans
  3007837944 # good, flowers, clouds, water, tree on the left
  3016047975 # a favorite, blue flowers, tracks, house, j truck, eats 6% of cpu (2 cores)
  3019470510 # a favorite stream in the forest, eats up to 18% cpu (6 cores)
  3029865244 # good, cozy bed, books, view of city
  3030685386 # a favorite, some weird artifacts though
  3036895455 # good, lake in the mountains, starry night
  3094852179 # good, dock, water, mountain
  3123321641 # a favorite, garden, stone construction
)

# Wallpaper command prefix
CMD_PREFIX="env XDG_SESSION_TYPE=wayland linux-wallpaperengine /home/gusjengis/Wallpapers/wallpaper_engine/"
SETTINGS="--assets-dir /home/gusjengis/Wallpapers/wallpaper_engine/assets --scaling fill --screen-root HDMI-A-1 --screen-root eDP-1 -v 0"

while true; do
  for id in $(shuf -e "${wallpapers[@]}"); do
    $CMD_PREFIX"$id"/ $SETTINGS &
    PID=$!
    sleep 300 # wallpaper duration (in seconds) 
    kill $PID 2>/dev/null
  done
done
