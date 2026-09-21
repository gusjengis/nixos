#!/usr/bin/env bash
# Reconcile ~/Wallpapers with origin: publish local curation, collect whatever
# the scheduled fetcher pushed.
#
# Two callers share this script. Ctrl+D in the picker runs it so a hide reaches
# the other machines promptly, and an hourly timer runs it to pick up new
# wallpapers from the GitHub Actions job. flock serialises the two, so a hide
# landing mid-pull cannot leave a half-rebased tree.
#
# Only curation.json is ever authored here. Images and metadata.json belong to
# the fetcher, and committing those from a workstation would race it.

set -euo pipefail

repo="${WALLPAPER_DIR:-$HOME/Wallpapers}"
lock="${XDG_RUNTIME_DIR:-/tmp}/wallpaper-sync.lock"

log() { printf 'wallpaper-sync: %s\n' "$1" >&2; }

if [ ! -d "$repo/.git" ]; then
  log "$repo is not a git repository, nothing to do"
  exit 0
fi

exec 9>"$lock"
if ! flock -w 180 9; then
  # Whoever holds the lock commits everything pending, including our change.
  log "another sync holds the lock, leaving it to that run"
  exit 0
fi

cd "$repo"

branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$branch" = "HEAD" ]; then
  log "detached HEAD, refusing to sync"
  exit 1
fi

# Coalescing falls out of committing whatever is pending rather than a specific
# change: several rapid Ctrl+D presses leave one commit for the first sync and
# nothing for the ones behind it.
if [ -n "$(git status --porcelain -- curation.json)" ]; then
  git add -- curation.json
  git commit -q -m "Update hidden wallpapers" -- curation.json
fi

if ! git fetch -q origin "$branch" 2>/dev/null; then
  log "fetch failed (offline?), will retry on the next run"
  exit 0
fi

# --autostash keeps an in-progress local fetch run's dirty metadata.json from
# blocking the rebase.
if ! git rebase -q --autostash "origin/$branch"; then
  git rebase --abort >/dev/null 2>&1 || true
  log "rebase onto origin/$branch failed, leaving the tree untouched"
  exit 1
fi

if [ -n "$(git rev-list "origin/$branch..HEAD")" ]; then
  if ! git push -q origin "$branch"; then
    log "push failed, will retry on the next run"
    exit 0
  fi
fi
