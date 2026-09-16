#!/usr/bin/env bash

SEARCH_DIR="/mnt/office/company/Jobs/Jobs"

[[ ! -d "$SEARCH_DIR" ]] && exit 1

selected=$(fd -t d -d 1 . --absolute-path "$SEARCH_DIR" 2>/dev/null \
  | sed "s|^$HOME/||" \
  | sk --color="bg:#0d1117,fg:#c9d1d9,matched:#58a6ff,matched_bg:#0d1117,current:#c9d1d9,current_bg:#161b22,current_match:#79c0ff,current_match_bg:#161b22,prompt:#58a6ff,pointer:#58a6ff,marker:#3fb950,spinner:#58a6ff,info:#8b949e,header:#8b949e,border:#30363d" --tmux center,50%)

[[ $selected ]] && [[ ! "$selected" =~ ^/ ]] && selected="$HOME/$selected"
[[ -z ${selected:-} ]] && exit 0

selected_name=$(create-tmux-session "$selected")
tmux switch-client -t "$selected_name"
