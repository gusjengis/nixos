#!/usr/bin/env bash
# Append the current battery level to a persistent history log.
#
# Driven by a systemd user timer so samples survive Hyprland/Quickshell
# restarts. Reads sysfs rather than acpi(1) for the same reason as
# battery-notify.sh: `acpi -b` also reports peripheral batteries, while sysfs
# exposes `scope`, which lets peripherals (mice, keyboards) be skipped.
set -euo pipefail

history_file="${XDG_STATE_HOME:-$HOME/.local/state}/quickshell/battery-history.log"

capacity=""

for supply in /sys/class/power_supply/*/; do
    [ -r "$supply/type" ] || continue
    [ "$(cat "$supply/type")" = "Battery" ] || continue

    # Peripheral batteries (mice, keyboards, headsets) report scope "Device".
    if [ -r "$supply/scope" ] && [ "$(cat "$supply/scope")" = "Device" ]; then
        continue
    fi

    [ -r "$supply/capacity" ] || continue

    capacity=$(cat "$supply/capacity")
    break
done

# No system battery: nothing to log.
if [ -z "$capacity" ]; then
    exit 0
fi

mkdir -p "$(dirname "$history_file")"
printf '%s %s\n' "$(date +%s%3N)" "$capacity" >> "$history_file"

# Keep the log bounded: drop samples older than a week.
cutoff=$(date -d '7 days ago' +%s%3N)
tmp="${history_file}.tmp"
awk -v cutoff="$cutoff" '$1 >= cutoff { print }' "$history_file" > "$tmp" \
    && mv "$tmp" "$history_file"