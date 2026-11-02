#!/bin/sh
# Root-owned LaunchDaemon: remote access remains reachable with the lid closed
# on AC, while normal sleep returns on battery. Never edits idle-sleep timers.
set -eu
last=
restore() { /usr/bin/pmset -a disablesleep 0; }
trap 'restore; exit 0' TERM INT HUP
trap restore EXIT
while :; do
    case "$(/usr/bin/pmset -g batt)" in
        "Now drawing from 'AC Power'"*) desired=1 ;;
        *) desired=0 ;;
    esac
    if [ "$desired" != "$last" ]; then
        /usr/bin/pmset -a disablesleep "$desired"
        last=$desired
    fi
    sleep 3 &
    wait $! || true
done
