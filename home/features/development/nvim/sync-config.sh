#!/usr/bin/env bash
# Keep the checked-out Neovim config in step with the commit this repository
# pins, in both directions.
#
# The config is a submodule so that a Home Manager generation names an exact
# Neovim config commit; without that, machines deploy the same flake yet run
# whatever the config repository happened to be at when they last pulled.
#
# It stays on its branch rather than the detached HEAD `git submodule update`
# would leave, because it is also a project you open and commit in directly.
set -euo pipefail

repo="${HM_REPO:-/etc/nixos}"
sub="${NVIM_CONFIG_SUBMODULE:-home/features/development/nvim/config}"
path="$repo/$sub"

warn() { echo "nvim-config-sync: $*" >&2; }

[ -d "$repo/.git" ] || {
  warn "$repo is not a Git repository"
  exit 0
}

pin="$(git -C "$repo" rev-parse ":$sub" 2>/dev/null || git -C "$repo" rev-parse "HEAD:$sub" 2>/dev/null || true)"
[ -n "$pin" ] || {
  warn "no submodule recorded at $sub"
  exit 0
}

# First deployment on this machine: no working tree yet.
if [ ! -e "$path/.git" ]; then
  git -C "$repo" submodule update --init --recursive -- "$sub"
  # Land on the branch instead of the detached HEAD checkout leaves behind.
  branch="$(git -C "$repo" config -f .gitmodules "submodule.$sub.branch" || echo master)"
  git -C "$path" checkout --quiet "$branch" 2>/dev/null || true
  exit 0
fi

current="$(git -C "$path" rev-parse HEAD)"
[ "$current" = "$pin" ] && exit 0

git -C "$path" fetch --quiet origin || warn "could not fetch origin for $sub"

# lazy-lock.json is generated state and deployment owns its value. Lazy may
# have rewritten a restore/install result into the working tree; never let that
# stale edit block moving the config repository onto the pinned commit.
git -C "$path" checkout -- lazy-lock.json

if git -C "$path" merge-base --is-ancestor "$current" "$pin"; then
  # This machine is behind the pin: fast-forward onto it.
  if [ -n "$(git -C "$path" status --porcelain)" ]; then
    warn "config has uncommitted changes, not moving it to $pin"
    exit 1
  fi
  git -C "$path" merge --ff-only --quiet "$pin"
  exit 0
fi

if git -C "$path" merge-base --is-ancestor "$pin" "$current"; then
  # This machine is ahead: publish the pointer so the others follow. Only for
  # commits that are already on the remote, otherwise the pointer would name a
  # commit no other machine can fetch.
  if [ -z "$(git -C "$path" branch --remotes --contains "$current" 2>/dev/null)" ]; then
    warn "config commit $current is not pushed yet, leaving the pin alone"
    exit 1
  fi

  git -C "$repo" add -- "$sub"
  git -C "$repo" commit --quiet -m "chore(nvim): bump config pointer" -- "$sub"
  git -C "$repo" push --quiet || warn "pointer committed but push failed, push $repo manually"
  exit 0
fi

warn "config at $current has diverged from the pinned $pin, resolve it by hand"
exit 1
