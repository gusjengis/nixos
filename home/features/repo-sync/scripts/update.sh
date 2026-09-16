#!/usr/bin/env bash
set -u
set -o pipefail

hm_repo="${HM_REPO:-/etc/nixos}"
sync_command="${SYNC_REPOS_COMMAND:-sync-repos}"
rebuild_command="${REBUILD_COMMAND:-rebuild}"
rehome_command="${REHOME_COMMAND:-rehome}"

state_dir="${XDG_RUNTIME_DIR:-/run/user/$UID}/home-manager-notifications"
log_file="$state_dir/update.log"
deployment_state_dir="${HM_DEPLOY_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/home-manager}"
deployed_revision_file="$deployment_state_dir/deployed-revision"
deployment_lock_file="$deployment_state_dir/update.lock"

notify() {
  local urgency="normal"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --urgency=*) urgency="${1#--urgency=}"; shift ;;
      -u|--urgency) urgency="${2:-normal}"; shift 2 ;;
      *) break ;;
    esac
  done

  mkdir -p "$state_dir"
  printf '%s\t%s\t%s\t%s\n' "$(date --iso-8601=seconds)" "$urgency" "${1:-update}" "${2:-}" >>"$log_file"
}

notify "update" "starting sync and rebuild checks"

failed=0

# A Home Manager activation holds this lock for its whole run, and activation
# is what starts this service. Without the guard the update would rebuild the
# system and re-activate Home Manager from inside the activation that launched
# it, which deadlocks against the user systemd manager.
mkdir -p "$deployment_state_dir"
exec 9>"$deployment_lock_file"
if ! flock -n 9; then
  notify "update" "activation or another update in progress, skipping"
  exit 0
fi

if [[ ! -d "$hm_repo/.git" ]]; then
  notify --urgency=critical "home-manager" "$hm_repo is not a Git repository"
  exit 1
fi

if [[ -n "$(git -C "$hm_repo" status --porcelain --ignore-submodules=all)" ]]; then
  notify "nixos-config" "uncommitted changes; skipping pull"
elif ! git -C "$hm_repo" fetch --quiet origin || ! git -C "$hm_repo" merge --quiet --ff-only '@{u}'; then
  notify --urgency=critical "nixos-config" "could not fast-forward $hm_repo"
  failed=1
fi

if ! "$sync_command"; then
  notify --urgency=critical "sync" "one or more repositories failed to sync"
  failed=1
fi

hm_after="$(git -C "$hm_repo" rev-parse HEAD)"
deployed_revision=""
if [[ -r "$deployed_revision_file" ]]; then
  deployed_revision="$(<"$deployed_revision_file")"
fi

if [[ "$deployed_revision" != "$hm_after" ]]; then
  if ! "$rebuild_command"; then
    notify --urgency=critical "nixos-rebuild" "unified configuration changed, rebuild failed"
    failed=1
  else
    notify "nixos-rebuild" "rebuild succeeded"
    if ! "$rehome_command"; then
      notify --urgency=critical "home-manager" "home-manager changed, switch failed"
      failed=1
    else
      notify "home-manager" "rehome succeeded"
      mkdir -p "$deployment_state_dir"
      printf '%s\n' "$hm_after" >"$deployed_revision_file.tmp"
      mv "$deployed_revision_file.tmp" "$deployed_revision_file"
    fi
  fi
fi

if [[ "$deployed_revision" == "$hm_after" ]]; then
  notify "update" "no repository changes found"
fi

if [[ "$failed" -ne 0 ]]; then
  notify --urgency=critical "update" "update completed with errors"
  exit 1
fi

notify "update" "update complete"
