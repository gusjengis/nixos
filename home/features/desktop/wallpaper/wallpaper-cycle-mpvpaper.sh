#!/usr/bin/env bash
set -euo pipefail

# store pid in a file so hyprland can signal it to change wallpaper
echo $$ > /tmp/wallpaper-script.pid

log_file="/tmp/gif_wallpaper_cycle_mpvpaper.log"
ambxst_wallpaper_state="${XDG_CACHE_HOME:-$HOME/.cache}/ambxst/wallpapers.json"
default_wallpaper_dir="$HOME/Wallpapers"
advance_request_file="/tmp/wallpaper-script.advance"

advance_requested=0
external_change_detected=0
cleaned_up=0

log_message() {
  printf '[%(%F %T)T] %s\n' -1 "$*" >> "$log_file"
}

next_wallpaper() {
  advance_requested=1
}

check_advance_request() {
  if [[ -f "$advance_request_file" ]]; then
    rm -f "$advance_request_file"
    next_wallpaper
  fi
}

wait_or_advance() {
  local seconds="$1"
  local expected_wall="$2"
  local elapsed=0

  external_change_detected=0

  while (( elapsed < seconds )); do
    check_advance_request

    if (( advance_requested )); then
      advance_requested=0
      return 0
    fi

    current_wall="$(read_state_current_wallpaper)"
    if [[ "$current_wall" != "$expected_wall" ]]; then
      external_change_detected=1
      return 1
    fi

    sleep 1 || true
    ((elapsed += 1))
  done

  advance_requested=0
  return 0
}

write_ambxst_wallpaper() {
  local img="$1"
  local wall_path="$2"

  mkdir -p "$(dirname "${ambxst_wallpaper_state}")"

  python3 - "$ambxst_wallpaper_state" "$wall_path" "$img" <<'PY'
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
            existing = json.load(fh)
        if isinstance(existing, dict):
            data.update(existing)
    except Exception:
        pass

data["wallPath"] = wall_path
data["currentWall"] = current_wall

with open(state_path, "w", encoding="utf-8") as fh:
    json.dump(data, fh, indent=4)
    fh.write("\n")
PY
}

cleanup() {
  local exit_code="${1:-0}"

  if (( cleaned_up )); then
    return
  fi

  cleaned_up=1
  rm -f /tmp/wallpaper-script.pid

  if (( exit_code == 0 )); then
    log_message "wallpaper cycle exiting cleanly"
  else
    log_message "wallpaper cycle exiting with status ${exit_code}"
  fi
}

scan_wallpapers() {
  python3 - "$ambxst_wallpaper_state" "$default_wallpaper_dir" <<'PY'
import json
import os
import sys

state_path, default_wall_path = sys.argv[1:3]
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

state = {}
if os.path.exists(state_path):
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            state = loaded
    except Exception:
        state = {}

wall_path = os.path.abspath(os.path.expanduser(state.get("wallPath") or default_wall_path))
current_wall = os.path.abspath(os.path.expanduser(state.get("currentWall") or ""))

wallpapers = []
if os.path.isdir(wall_path):
    for root, dirnames, filenames in os.walk(wall_path):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in extensions:
                wallpapers.append(os.path.join(root, name))

resolved_current = current_wall if current_wall in wallpapers else (wallpapers[0] if wallpapers else "")

print(wall_path)
print(resolved_current)
for wallpaper in wallpapers:
    print(wallpaper)
PY
}

read_current_wallpaper() {
  local scanned

  mapfile -t scanned < <(scan_wallpapers)
  printf '%s\n' "${scanned[1]:-}"
}

read_state_current_wallpaper() {
  python3 - "$ambxst_wallpaper_state" <<'PY'
import json
import os
import sys

state_path = sys.argv[1]
current_wall = ""

if os.path.exists(state_path):
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            current_wall = loaded.get("currentWall") or ""
    except Exception:
        pass

print(os.path.abspath(os.path.expanduser(current_wall)) if current_wall else "")
PY
}

select_next_wallpaper() {
  local scanned
  local wall_path
  local current_wall
  local next_wall=""
  local wallpapers=()
  local i

  mapfile -t scanned < <(scan_wallpapers)
  wall_path="${scanned[0]:-$default_wallpaper_dir}"
  current_wall="${scanned[1]:-}"

  if (( ${#scanned[@]} > 2 )); then
    wallpapers=("${scanned[@]:2}")
  fi

  if (( ${#wallpapers[@]} == 0 )); then
    printf '\n%s\n' "$wall_path"
    return 0
  fi

  for i in "${!wallpapers[@]}"; do
    if [[ "${wallpapers[$i]}" == "$current_wall" ]]; then
      next_wall="${wallpapers[$(((i + 1) % ${#wallpapers[@]}))]}"
      break
    fi
  done

  if [[ -z "$next_wall" ]]; then
    next_wall="${wallpapers[0]}"
  fi

  printf '%s\n%s\n' "$next_wall" "$wall_path"
}

trap 'log_message "received termination signal"; cleanup 0; exit 0' INT TERM HUP
trap 'log_message "command failed at line $LINENO"' ERR
trap 'cleanup $?' EXIT

log_message "wallpaper cycle started"

while true; do
  mapfile -t scanned < <(scan_wallpapers)
  wall_path="${scanned[0]:-$default_wallpaper_dir}"
  current_img="${scanned[1]:-}"

  if [[ -z "$current_img" ]]; then
    mapfile -t selection < <(select_next_wallpaper)
    img="${selection[0]:-}"

    if [[ -z "$img" ]]; then
      if ! wait_or_advance 60 ""; then
        continue
      fi

      continue
    fi

    write_ambxst_wallpaper "$img" "$wall_path"
    current_img="$img"
  fi

  if ! wait_or_advance 300 "$current_img"; then
    if (( external_change_detected )); then
      continue
    fi

    continue
  fi

  mapfile -t selection < <(select_next_wallpaper)
  img="${selection[0]:-}"
  wall_path="${selection[1]:-$default_wallpaper_dir}"

  if [[ -z "$img" ]]; then
    continue
  fi

  write_ambxst_wallpaper "$img" "$wall_path"
done
