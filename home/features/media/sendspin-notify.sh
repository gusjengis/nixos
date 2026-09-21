#!/usr/bin/env bash

set -uo pipefail

notify_pairing_pin() {
  local pin=$1
  local action

  if action=$(notify-send \
    --app-name=Sendspin \
    --urgency=critical \
    --expire-time=0 \
    --action=default="Copy PIN" \
    "Sendspin pairing PIN: $pin" \
    "Click this notification to copy the PIN for Music Assistant."); then
    if [[ $action == default ]]; then
      printf '%s' "$pin" | wl-copy
    fi
  fi
}

pin_pattern='Pairing required: enter PIN ([0-9]+) on the server\.'

"$@" 2>&1 | while IFS= read -r line || [[ -n $line ]]; do
  printf '%s\n' "$line"
  if [[ $line =~ $pin_pattern ]]; then
    notify_pairing_pin "${BASH_REMATCH[1]}" &
  fi
done
