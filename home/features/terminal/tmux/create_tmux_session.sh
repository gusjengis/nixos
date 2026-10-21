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

if [[ ${3:-} == --attach ]]; then
  exec tmux attach-session -t "=$session"
fi

printf '%s\n' "$session"
