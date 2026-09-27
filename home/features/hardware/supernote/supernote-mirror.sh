#!/usr/bin/env bash

set -euo pipefail

DEVICE_PATTERN='Supernote_Nomad|Supernote_A5X|Supernote_A6X'
ADB_PORT=18080
DEVICE_PORT=18880
MIRROR_PORT=8080
RELAY_PID_FILE="${XDG_RUNTIME_DIR:-/tmp}/supernote-mirror-relay.pid"

device() {
  adb devices -l | awk -v pattern="$DEVICE_PATTERN" '$0 ~ pattern && $2 == "device" {print $1; exit}'
}

mirror_ready() {
  local page
  page=$(curl --http0.9 -fsS --max-time 1 "http://127.0.0.1:$ADB_PORT/" 2>/dev/null) || return 1
  [[ "$page" == *'Supernote Screen Mirroring'* ]]
}

cleanup() {
  local serial
  serial=$(device || true)
  if [[ -n "$serial" ]]; then
    adb -s "$serial" shell "pkill -f 'nc -L -p $DEVICE_PORT'" >/dev/null 2>&1 || true
    adb -s "$serial" forward --remove "tcp:$ADB_PORT" >/dev/null 2>&1 || true
  else
    adb forward --remove "tcp:$ADB_PORT" >/dev/null 2>&1 || true
  fi
  if [[ -f "$RELAY_PID_FILE" ]]; then
    kill "$(<"$RELAY_PID_FILE")" >/dev/null 2>&1 || true
    rm -f "$RELAY_PID_FILE"
  fi
}

stop() {
  cleanup
}

start() {
  local serial ip
  serial=$(device || true)
  if [[ -z "$serial" ]]; then
    return 1
  fi

  ip=$(adb -s "$serial" shell 'ip -4 -o addr show wlan0' | awk '{split($4,a,"/"); print a[1]}')
  if [[ -z "$ip" ]]; then
    return 1
  fi

  if mirror_ready; then
    return 0
  fi

  cleanup
  adb -s "$serial" shell "toybox nc -L -p $DEVICE_PORT toybox nc $ip $MIRROR_PORT" &
  echo $! > "$RELAY_PID_FILE"
  adb -s "$serial" forward "tcp:$ADB_PORT" "tcp:$DEVICE_PORT"

  for _ in $(seq 1 20); do
    if mirror_ready; then
      return 0
    fi
    sleep 0.25
  done
  cleanup
  return 1
}

open_app() {
  start
  exec chromium --app="http://127.0.0.1:$ADB_PORT/" --class=supernote-mirror
}

case "${1:-}" in
  run)
    until start; do
      [[ -n "$(device || true)" ]] || exit 0
      sleep 5
    done
    (
      action=$(notify-send --app-name=Supernote --urgency=normal --expire-time=0 --action=default='Open mirror' "Supernote mirror ready" "Click to open screen preview." || true)
      [[ "$action" == default ]] && chromium --app="http://127.0.0.1:$ADB_PORT/" --class=supernote-mirror
    ) >/dev/null 2>&1 </dev/null &
    while [[ -n "$(device || true)" ]]; do sleep 2; done
    ;;
  stop) stop ;;
  open) open_app ;;
  notify)
    action=$(notify-send --app-name=Supernote --urgency=normal --expire-time=0 --action=default='Open mirror' "Supernote mirror ready" "Click to open screen preview.")
    [[ "$action" == default ]] && exec chromium --app="http://127.0.0.1:$ADB_PORT/" --class=supernote-mirror
    ;;
  *) printf 'usage: supernote-mirror {run|stop|open|notify}\n' >&2; exit 2 ;;
esac
