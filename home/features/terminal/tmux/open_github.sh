#!/usr/bin/env bash

# Open the current repository in the browser
dir=$(tmux run "echo #{pane_start_path}" 2>/dev/null)
cd "$dir" || exit 1

url=$(git remote get-url origin 2>/dev/null)

# Check if the repository is on GitHub
if [[ $url == *"github.com"* ]]; then
  xdg-open "$url" >/dev/null 2>&1 &
else
  echo "This repository is not hosted on GitHub" >&2
fi
