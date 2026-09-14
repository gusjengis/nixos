#!/usr/bin/env bash

DIRS=(
  "$HOME/Documents/Code"
  "$HOME/Documents/Code/Plinth"
  "$HOME/Documents/Code/Mosaic"
  "$HOME/Documents/Obsidian"
  "$HOME/wkspaces/"
)

EXTRA_DIRS=(
  "$HOME/Wallpapers"
  "$HOME/.config/nvim"
  "$HOME/.config/secrets"
  "$HOME/.home-manager/"
  "/etc/nixos"

)

IGNORE_DIRS=(
  "$HOME/wkspaces/Cross The Line/"
)

filter_ignored_dirs() {
  local entry

  while IFS= read -r entry; do
    [[ -z $entry ]] && continue

    if [[ " ${IGNORE_DIRS[*]} " == *" $entry "* ]]; then
      continue
    fi

    printf "%s\n" "$entry"
  done
}

expand_path() {
  local path=$1

  case $path in
    "~") printf "%s\n" "$HOME" ;;
    "~/"*) printf "%s/%s\n" "$HOME" "${path#~/}" ;;
    *) printf "%s\n" "$path" ;;
  esac
}

build_fd_entries() {
  local dirs=()
  local dir

  for dir in "$@"; do
    dirs+=("$(expand_path "$dir")")
  done

  fd -t d -d 1 . --absolute-path "${dirs[@]}" 2>/dev/null \
    | filter_ignored_dirs \
    | sed "s|^$HOME/||"
}

if [[ $# -gt 0 ]]; then
  fd_entries=$(build_fd_entries "$@")
  selected=$(
    printf "%s\n" "$fd_entries" \
    | sk --color="bg:#0d1117,fg:#c9d1d9,matched:#58a6ff,matched_bg:#0d1117,current:#c9d1d9,current_bg:#161b22,current_match:#79c0ff,current_match_bg:#161b22,prompt:#58a6ff,pointer:#58a6ff,marker:#3fb950,spinner:#58a6ff,info:#8b949e,header:#8b949e,border:#30363d" --tmux center,50%
  )
  [[ $selected ]] && [[ ! "$selected" =~ ^/ ]] && selected="$HOME/$selected"
else
  fd_entries=$(
    build_fd_entries "${DIRS[@]}"
  )
  extra_entries=$(
    printf "%s\n" "${EXTRA_DIRS[@]}" \
    | filter_ignored_dirs \
    | sed "s|^$HOME/||"
  )
  selected=$(
    printf "%s\n" "$fd_entries" "$extra_entries" \
    | sk --color="bg:#0d1117,fg:#c9d1d9,matched:#58a6ff,matched_bg:#0d1117,current:#c9d1d9,current_bg:#161b22,current_match:#79c0ff,current_match_bg:#161b22,prompt:#58a6ff,pointer:#58a6ff,marker:#3fb950,spinner:#58a6ff,info:#8b949e,header:#8b949e,border:#30363d" --tmux center,50%
  )
  [[ $selected ]] && [[ ! "$selected" =~ ^/ ]] && selected="$HOME/$selected"
fi

[[ -z ${selected:-} ]] && exit 0

selected_name=$(create-tmux-session "$selected")
tmux switch-client -t "$selected_name"
