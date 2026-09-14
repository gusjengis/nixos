#!/usr/bin/env bash

set -euo pipefail

project=${1:?usage: create-tmux-session PROJECT}
project=$(realpath "$project")
session=$(basename "$project" | tr . _)

if ! tmux has-session -t "$session" 2>/dev/null; then
  tmux new-session -ds "$session" -c "$project" "nvim ."
  tmux new-window -t "$session" -n "opencode" -c "$project" "opencode"
  tmux select-window -t "$session:1"
fi

printf '%s\n' "$session"
