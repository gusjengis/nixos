#!/usr/bin/env bash
# Warn once when the system battery falls to the threshold while discharging.
#
# Reads sysfs rather than acpi(1) on purpose. `acpi -b` also reports peripheral
# batteries, so on the Apple Silicon laptop it lists the Logitech mouse as
# "Battery 1: Unknown, 0%" next to the real one. sysfs exposes `scope`, which
# lets peripherals be skipped, and it works on macsmc-battery as well as ACPI.
set -euo pipefail

threshold="${BATTERY_WARN_PERCENT:-15}"
state_file="${XDG_CACHE_HOME:-$HOME/.cache}/battery-notify-warned"

capacity=""
status=""

for supply in /sys/class/power_supply/*/; do
    [ -r "$supply/type" ] || continue
    [ "$(cat "$supply/type")" = "Battery" ] || continue

    # Peripheral batteries (mice, keyboards, headsets) report scope "Device".
    if [ -r "$supply/scope" ] && [ "$(cat "$supply/scope")" = "Device" ]; then
        continue
    fi

    [ -r "$supply/capacity" ] && [ -r "$supply/status" ] || continue

    capacity=$(cat "$supply/capacity")
    status=$(cat "$supply/status")
    break
done

# No system battery: nothing to warn about.
if [ -z "$capacity" ]; then
    exit 0
fi

if [ "$status" != "Discharging" ] || [ "$capacity" -gt "$threshold" ]; then
    rm -f "$state_file"
    exit 0
fi

if [ ! -e "$state_file" ]; then
    notify-send --urgency=critical "Battery Low" "Battery at ${capacity}% - please charge"
    mkdir -p "$(dirname "$state_file")"
    touch "$state_file"
fi
