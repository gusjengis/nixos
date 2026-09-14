#!/usr/bin/env bash

set -uo pipefail

state_dir="${XDG_RUNTIME_DIR:-/tmp}/opencode-session-notify-$UID"
umask 077
mkdir -p "$state_dir"

close_notification() {
  local id=$1
  [[ $id =~ ^[0-9]+$ ]] || return 0
  gdbus call --session \
    --dest org.freedesktop.Notifications \
    --object-path /org/freedesktop/Notifications \
    --method org.freedesktop.Notifications.CloseNotification \
    "$id" >/dev/null 2>&1 || true
}

close_matching() {
  local field=$1
  local wanted=$2
  local completion_only=${3:-0}
  local meta base id
  local -a values
  local matched=1

  shopt -s nullglob
  for meta in "$state_dir"/*.meta; do
    mapfile -t values < "$meta"
    [[ ${values[$field]:-} == "$wanted" ]] || continue
    if (( completion_only )) && [[ -n ${values[2]:-} ]]; then
      continue
    fi
    matched=0
    base=${meta%.meta}
    : > "$base.close"
    if [[ -s $base.id ]]; then
      IFS= read -r id < "$base.id"
      close_notification "$id"
    fi
  done
  return "$matched"
}

if [[ ${1:-} == --close-pane || ${1:-} == --close-session || ${1:-} == --close-request ]]; then
  [[ $# -eq 2 ]] || exit 2
  case $1 in
    --close-pane) field=0; completion_only=1 ;;
    --close-session) field=1 ;;
    --close-request) field=2 ;;
  esac
  # Spawn and close helpers start independently. Brief retry covers a reply
  # arriving before the notification helper has published its metadata.
  for _attempt in {1..50}; do
    close_matching "$field" "$2" "${completion_only:-0}" && exit 0
    sleep 0.01
  done
  exit 0
fi

activate_only=0
if [[ ${1:-} == --activate ]]; then
  activate_only=1
  shift
fi

if [[ $# -ne 12 ]]; then
  printf 'usage: opencode-session-notify [--activate] TITLE BODY URGENCY DIRECTORY OPENCODE_SESSION TMUX_PANE TMUX_SESSION_ID TMUX_SESSION_NAME TMUX_CLIENT OPENCODE_PID OPENCODE_START_TIME REQUEST_ID\n' >&2
  exit 2
fi

title=$1
body=$2
urgency=$3
directory=$4
opencode_session=$5
origin_pane=$6
origin_session_id=$7
origin_session_name=$8
origin_client=$9
opencode_pid=${10}
opencode_start_time=${11}
request_id=${12}

if (( ! activate_only )); then
  notification_state="$state_dir/notification-$$"
  cleanup_notification_state() {
    rm -f "$notification_state.meta" "$notification_state.id" \
      "$notification_state.action" "$notification_state.close"
  }
  trap cleanup_notification_state EXIT
  printf '%s\n%s\n%s\n' "$origin_pane" "$opencode_session" "$request_id" > "$notification_state.meta"
  notify-send -u "$urgency" --action=default=Focus \
    --id-fd=3 --selected-action-fd=4 "$title" "$body" \
    3> "$notification_state.id" 4> "$notification_state.action" 2>/dev/null &
  notify_pid=$!

  while kill -0 "$notify_pid" 2>/dev/null && [[ ! -s $notification_state.id ]]; do
    sleep 0.01
  done
  if [[ -e $notification_state.close && -s $notification_state.id ]]; then
    IFS= read -r notification_id < "$notification_state.id"
    close_notification "$notification_id"
  fi

  wait "$notify_pid" || exit 0
  IFS= read -r action < "$notification_state.action" || action=
  cleanup_notification_state
  trap - EXIT
  [[ $action == default ]] || exit 0
fi

tmux_display() {
  tmux display-message -p -t "$1" "$2" 2>/dev/null
}

session_exists() {
  [[ -n $1 ]] && tmux has-session -t "$1" 2>/dev/null
}

# Boot-relative start time distinguishes the original OpenCode process from an
# unrelated process that later reused its pid.
process_start_time() {
  local pid=$1
  local stat fields
  [[ -r /proc/$pid/stat ]] || return 1
  IFS= read -r stat < "/proc/$pid/stat" || return 1
  read -ra fields <<< "${stat##*) }"
  printf '%s\n' "${fields[19]}"
}

client_exists() {
  local wanted=$1
  local client
  [[ -n $wanted ]] || return 1
  while IFS= read -r client; do
    [[ $client == "$wanted" ]] && return 0
  done < <(tmux list-clients -F '#{client_name}' 2>/dev/null)
  return 1
}

process_has_ancestor() {
  local pid=$1
  local wanted=$2
  local stat rest

  while (( pid > 1 )); do
    [[ $pid == "$wanted" ]] && return 0
    [[ -r /proc/$pid/stat ]] || return 1
    IFS= read -r stat < "/proc/$pid/stat" || return 1
    rest=${stat##*) }
    pid=${rest#* }
    pid=${pid%% *}
  done
  return 1
}

hyprland_instance() {
  local instances
  instances=$(hyprctl instances -j 2>/dev/null) || return 1
  if [[ -n ${HYPRLAND_INSTANCE_SIGNATURE:-} ]] \
      && jq -e --arg instance "$HYPRLAND_INSTANCE_SIGNATURE" \
        'any(.instance == $instance)' <<< "$instances" >/dev/null 2>&1; then
    printf '%s\n' "$HYPRLAND_INSTANCE_SIGNATURE"
    return
  fi
  jq -r 'max_by(.time) | .instance // empty' <<< "$instances" 2>/dev/null
}

hyprland_clients() {
  local instance=$1
  HYPRLAND_INSTANCE_SIGNATURE=$instance hyprctl clients -j 2>/dev/null
}

window_for_tmux_client() {
  local client=$1
  local instance=$2
  local client_pid window_pid address

  client_pid=$(tmux display-message -p -c "$client" '#{client_pid}' 2>/dev/null) || return 1
  while IFS=$'\t' read -r window_pid address; do
    if process_has_ancestor "$client_pid" "$window_pid"; then
      printf '%s\n' "$address"
      return 0
    fi
  done < <(hyprland_clients "$instance" | jq -r '.[] | [.pid, .address] | @tsv' 2>/dev/null)
  return 1
}

latest_local_client_for_session() {
  local session=$1
  local instance=$2
  local address
  tmux list-clients -F $'#{client_activity}\t#{client_name}\t#{client_session}' 2>/dev/null \
    | sort -nr \
    | while IFS=$'\t' read -r _activity client client_session; do
      if [[ $client_session == "$session" ]]; then
        if [[ -z $instance ]]; then
          printf '%s\n' "$client"
          exit 0
        fi
        address=$(window_for_tmux_client "$client" "$instance")
        if [[ -n $address ]]; then
          printf '%s\n' "$client"
          exit 0
        fi
      fi
    done
}

latest_hyprland_tmux_client() {
  local instance=$1
  local clients client_pid client window_pid _address
  clients=$(hyprland_clients "$instance") || return 1

  while IFS=$'\t' read -r _activity client client_pid; do
    while IFS=$'\t' read -r window_pid _address; do
      if process_has_ancestor "$client_pid" "$window_pid"; then
        printf '%s\n' "$client"
        return 0
      fi
    done < <(jq -r '.[] | select(.workspace.name == "special:terminal") | [.pid, .address] | @tsv' <<< "$clients" 2>/dev/null)
  done < <(tmux list-clients -F $'#{client_activity}\t#{client_name}\t#{client_pid}' 2>/dev/null | sort -nr)
  return 1
}

lua_string() {
  local value=$1
  value=${value//\\/\\\\}
  value=${value//\"/\\\"}
  printf '"%s"' "$value"
}

focus_window() {
  local instance=$1
  local address=$2
  local output
  output=$(HYPRLAND_INSTANCE_SIGNATURE=$instance hyprctl dispatch \
    "hl.dsp.focus({ window = $(lua_string "address:$address") })" 2>/dev/null) || return 1
  [[ $output == ok ]]
}

open_terminal() {
  local instance=$1
  local session=$2
  local command command_lua workspace_lua output
  printf -v command '%q ' kitty tmux attach-session -t "$session"
  command=${command% }
  command_lua=$(lua_string "$command")
  workspace_lua=$(lua_string 'special:terminal')

  if [[ -n $instance ]]; then
    output=$(HYPRLAND_INSTANCE_SIGNATURE=$instance hyprctl dispatch \
      "hl.dsp.exec_cmd($command_lua, { workspace = $workspace_lua })" 2>/dev/null) || return 1
    [[ $output == ok ]] || return 1
    for _attempt in {1..100}; do
      if hyprland_clients "$instance" \
          | jq -e 'any(.workspace.name == "special:terminal")' >/dev/null 2>&1; then
        break
      fi
      sleep 0.02
    done
    output=$(HYPRLAND_INSTANCE_SIGNATURE=$instance hyprctl dispatch \
      "hl.dsp.focus({ workspace = $workspace_lua })" 2>/dev/null) || return 1
    [[ $output == ok ]]
  else
    kitty tmux attach-session -t "$session" >/dev/null 2>&1 &
  fi
}

if [[ ! -d $directory ]]; then
  exit 0
fi

target_pane=
target_session=
if [[ -n $origin_pane ]]; then
  pane_pid=$(tmux_display "$origin_pane" '#{pane_pid}') || pane_pid=
  current_start_time=$(process_start_time "$opencode_pid") || current_start_time=
  if [[ -n $pane_pid && -n $opencode_start_time \
      && $current_start_time == "$opencode_start_time" ]] \
      && process_has_ancestor "$opencode_pid" "$pane_pid"; then
    target_pane=$origin_pane
    target_session=$(tmux_display "$origin_pane" '#{session_id}') || target_session=
  fi
fi

if [[ -z $target_pane ]]; then
  lock_name=${opencode_session:-$(basename "$directory")}
  lock_name=${lock_name//[^a-zA-Z0-9_-]/_}
  exec 9>"${XDG_RUNTIME_DIR:-/tmp}/opencode-session-notify-$lock_name.lock"
  flock 9

  if [[ -n $opencode_session ]]; then
    while IFS=$'\t' read -r pane tagged_session; do
      if [[ $tagged_session == "$opencode_session" ]]; then
        target_pane=$pane
        target_session=$(tmux_display "$pane" '#{session_id}') || target_session=
        break
      fi
    done < <(tmux list-panes -a -F $'#{pane_id}\t#{@opencode_session_id}' 2>/dev/null)
  fi

  if [[ -z $target_pane ]]; then
    command=(opencode "$directory")
    [[ -n $opencode_session ]] && command+=(--session "$opencode_session")
    printf -v shell_command '%q ' "${command[@]}"
    shell_command=${shell_command% }

    # Exact-match targets ("=name") keep a dead session's name from resolving to
    # an unrelated live session that merely shares its prefix.
    if session_exists "$origin_session_id"; then
      target_session=$origin_session_id
    elif [[ -n $origin_session_name ]] && session_exists "=$origin_session_name"; then
      target_session="=$origin_session_name"
    else
      target_session=${origin_session_name:-$(basename "$directory" | tr '.:' '__')}
      target_pane=$(tmux new-session -d -P -F '#{pane_id}' -s "$target_session" -n opencode \
        -c "$directory" "$shell_command") || exit 0
    fi

    if [[ -z $target_pane ]]; then
      target_pane=$(tmux new-window -d -P -F '#{pane_id}' -t "$target_session:" -n opencode \
        -c "$directory" "$shell_command") || exit 0
    fi
  fi

  if [[ -n $opencode_session ]]; then
    tmux set-option -p -t "$target_pane" @opencode_session_id "$opencode_session" 2>/dev/null || true
  fi
  flock -u 9
fi

tmux select-window -t "$target_pane" 2>/dev/null || true
tmux select-pane -t "$target_pane" 2>/dev/null || true

target_session_name=$(tmux_display "$target_pane" '#{session_name}') || exit 0
instance=$(hyprland_instance)
client=
if client_exists "$origin_client"; then
  if [[ -z $instance ]] || [[ -n $(window_for_tmux_client "$origin_client" "$instance") ]]; then
    client=$origin_client
  fi
fi
if [[ -z $client ]]; then
  client=$(latest_local_client_for_session "$target_session_name" "$instance")
fi

if [[ -z $client && -n $instance ]]; then
  client=$(latest_hyprland_tmux_client "$instance")
fi

if [[ -n $client ]]; then
  tmux switch-client -c "$client" -t "$target_pane" 2>/dev/null || exit 0
  if [[ -n $instance ]]; then
    address=$(window_for_tmux_client "$client" "$instance")
    [[ -n $address ]] && focus_window "$instance" "$address" || true
  fi
else
  open_terminal "$instance" "$target_session_name"
fi
