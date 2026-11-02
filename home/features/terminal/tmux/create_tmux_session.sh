#!/usr/bin/env bash

set -euo pipefail

project=${1:?usage: create-tmux-session PROJECT [SESSION [--attach]]}
project=$(realpath "$project")
session=${2:-$(basename "$project" | tr . _)}
environment=()
for variable in CONTEXT_DIRECTORY CONTEXT_ID; do
  if [[ -n ${!variable:-} ]]; then
    environment+=(-e "$variable=${!variable}")
  fi
done

if [[ -f "$project/flake.nix" && -f "$project/.envrc" ]]; then
  direnv allow "$project"
fi

if ! tmux has-session -t "=$session" 2>/dev/null; then
  tmux new-session -ds "$session" "${environment[@]}" -c "$project" "nvim ."
  tmux new-window -t "$session" -n "opencode" -c "$project" "opencode"
  tmux select-window -t "$session:1"
fi

# A restored session may have been created in its context's state directory.
# A short-lived control client updates the native default without moving panes
# or switching any attached terminal. -E preserves the session environment.
TMUX= tmux -C attach-session -E -t "=$session" -c "${project//#/##}" \; detach-client </dev/null >/dev/null

if [[ ${3:-} == --attach ]]; then
  exec tmux attach-session -t "=$session"
fi

printf '%s\n' "$session"
