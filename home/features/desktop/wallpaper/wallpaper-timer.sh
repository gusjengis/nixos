#!/usr/bin/env bash
set -euo pipefail

interval_seconds="${WALLPAPER_INTERVAL_SECONDS:-300}"
state_file="${XDG_CACHE_HOME:-$HOME/.cache}/ambxst/wallpapers.json"
default_wallpaper_dir="$HOME/Wallpapers"
lock_dir="/tmp/ambxst_wallpaper_timer.lock"

shell_ready() {
  pgrep -f 'quickshell|ambxst|mpvpaper' >/dev/null 2>&1
}

acquire_lock() {
  if mkdir "$lock_dir" 2>/dev/null; then
    printf '%s\n' "$$" > "$lock_dir/pid"
    return 0
  fi

  existing_pid=""
  if [[ -f "$lock_dir/pid" ]]; then
    existing_pid="$(<"$lock_dir/pid")"
  fi

  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    return 1
  fi

  rm -rf "$lock_dir"
  mkdir "$lock_dir"
  printf '%s\n' "$$" > "$lock_dir/pid"
}

read_state() {
  python3 - "$state_file" "$default_wallpaper_dir" <<'PY'
import json
import os
import sys

state_path, default_path = sys.argv[1:3]
wall_path = os.path.abspath(os.path.expanduser(default_path))
current_wall = ""
mtime_ns = 0

if os.path.exists(state_path):
    try:
        mtime_ns = os.stat(state_path).st_mtime_ns
    except OSError:
        mtime_ns = 0

    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            wall_path = os.path.abspath(os.path.expanduser(loaded.get("wallPath") or default_path))
            current_wall = loaded.get("currentWall") or ""
    except Exception:
        pass

if current_wall:
    current_wall = os.path.abspath(os.path.expanduser(current_wall))

print(wall_path)
print(current_wall)
print(mtime_ns)
PY
}

pick_random_wallpaper() {
  python3 - "$1" "$2" <<'PY'
import os
import random
import sys

wall_path = os.path.abspath(os.path.expanduser(sys.argv[1]))
current_wall = os.path.abspath(os.path.expanduser(sys.argv[2])) if sys.argv[2] else ""
extensions = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".gif",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mkv",
}

wallpapers = []
if os.path.isdir(wall_path):
    for root, dirnames, filenames in os.walk(wall_path):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in extensions:
                wallpapers.append(os.path.join(root, name))

if not wallpapers:
    print("")
    raise SystemExit(0)

candidates = [path for path in wallpapers if path != current_wall]
pool = candidates or wallpapers
print(random.SystemRandom().choice(pool))
PY
}

write_current_wallpaper() {
  python3 - "$state_file" "$1" "$2" <<'PY'
import json
import os
import sys

state_path, wall_path, current_wall = sys.argv[1:4]
data = {
    "activeColorPreset": "",
    "currentWall": current_wall,
    "matugenScheme": "scheme-tonal-spot",
    "tintEnabled": False,
    "wallPath": wall_path,
}

if os.path.exists(state_path):
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            data.update(loaded)
    except Exception:
        pass

data["wallPath"] = wall_path
data["currentWall"] = current_wall

os.makedirs(os.path.dirname(state_path), exist_ok=True)
with open(state_path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=4)
    fh.write("\n")
PY
}

wait_for_initial_wallpaper() {
  local wall_path
  local current_wall
  local state_mtime

  while true; do
    mapfile -t state < <(read_state)
    wall_path="${state[0]:-$default_wallpaper_dir}"
    current_wall="${state[1]:-}"
    state_mtime="${state[2]:-0}"

    if shell_ready && [[ -n "$current_wall" ]] && [[ -e "$current_wall" ]]; then
      printf '%s\n%s\n%s\n' "$wall_path" "$current_wall" "$state_mtime"
      return 0
    fi

    sleep 2
  done
}

trap 'exit 0' INT TERM HUP
trap 'rm -rf "$lock_dir"' EXIT

if ! acquire_lock; then
  exit 0
fi

mapfile -t state < <(wait_for_initial_wallpaper)
wall_path="${state[0]:-$default_wallpaper_dir}"
last_current="${state[1]:-}"
last_mtime="${state[2]:-0}"
deadline="$(( $(date +%s) + interval_seconds ))"

while true; do
  mapfile -t state < <(read_state)
  wall_path="${state[0]:-$default_wallpaper_dir}"
  current_wall="${state[1]:-}"
  state_mtime="${state[2]:-0}"
  now="$(date +%s)"

  if ! shell_ready || [[ -z "$current_wall" ]] || [[ ! -e "$current_wall" ]]; then
    mapfile -t state < <(wait_for_initial_wallpaper)
    wall_path="${state[0]:-$default_wallpaper_dir}"
    last_current="${state[1]:-}"
    last_mtime="${state[2]:-0}"
    deadline="$(( $(date +%s) + interval_seconds ))"
    sleep 1
    continue
  fi

  if [[ "$state_mtime" != "$last_mtime" ]] || [[ "$current_wall" != "$last_current" ]]; then
    last_current="$current_wall"
    last_mtime="$state_mtime"
    deadline="$(( now + interval_seconds ))"
    sleep 1
    continue
  fi

  if (( now < deadline )); then
    sleep 1
    continue
  fi

  next_wall="$(pick_random_wallpaper "$wall_path" "$current_wall")"
  if [[ -z "$next_wall" ]] || [[ "$next_wall" == "$current_wall" ]]; then
    deadline="$(( now + interval_seconds ))"
    sleep 1
    continue
  fi

  write_current_wallpaper "$wall_path" "$next_wall"

  mapfile -t state < <(read_state)
  last_current="${state[1]:-$next_wall}"
  last_mtime="${state[2]:-0}"
  deadline="$(( $(date +%s) + interval_seconds ))"
  sleep 1
done
