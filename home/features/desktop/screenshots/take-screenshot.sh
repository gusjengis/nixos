#!/usr/bin/env bash
set -euo pipefail

mode="${1:-}"
output_dir="${2:-$HOME/Pictures/Screenshots}"

if ! command -v hyprctl >/dev/null 2>&1; then
  printf 'Missing required command: hyprctl\n' >&2
  exit 1
fi

mkdir -p "$output_dir"

geometry=""
output=""

case "$mode" in
  output)
    output="$(slurp -o -f '%o')" || exit 0
    ;;
  region)
    geometry="$(slurp -f '%x,%y %wx%h')" || exit 0
    ;;
  window)
    windows="$(
      hyprctl -j clients | jq -r '
        .[]
        | select(.mapped and (.hidden | not) and (.workspace.id > 0))
        | "\(.at[0]),\(.at[1]) \(.size[0])x\(.size[1])"
      '
    )"

    if [[ -z "$windows" ]]; then
      printf 'No visible windows to select\n' >&2
      exit 1
    fi

    geometry="$(printf '%s\n' "$windows" | slurp -r -f '%x,%y %wx%h')" || exit 0
    ;;
  *)
    printf 'Usage: %s <output|region|window> [output_dir]\n' "$0" >&2
    exit 2
    ;;
esac

timestamp="$(date '+%Y-%m-%d %H-%M-%S')"
outfile="$output_dir/Screenshot from $timestamp.png"

if [[ -n "$output" ]]; then
  grim -o "$output" "$outfile"
else
  grim -g "$geometry" "$outfile"
fi

wl-copy --type image/png <"$outfile"
notify-send "Screenshot saved" "$outfile"
