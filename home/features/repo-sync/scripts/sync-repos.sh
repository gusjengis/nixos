#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_LIST_DIR="${REPO_LIST_DIR:-$SCRIPT_DIR/../repos}"
CLONE_REPO_LIB="${CLONE_REPO_LIB:-$SCRIPT_DIR/clone-repo.sh}"
SYNC_REPO_GROUPS="${SYNC_REPO_GROUPS:-core}"

# shellcheck source=/dev/null
source "$CLONE_REPO_LIB"

if ! command -v git >/dev/null 2>&1; then
    echo "git is not installed or not on PATH."
    exit 1
fi

if ! command -v gh >/dev/null 2>&1; then
    echo "GitHub CLI (gh) is not installed or not on PATH."
    exit 1
fi

# Load the token directly rather than relying on the shell environment: this
# script also runs from systemd at boot, where no one can answer a prompt.
if [ -z "${GH_TOKEN:-}" ] && [ -r "$HOME/.config/secrets/PAT" ]; then
    GH_TOKEN="$(< "$HOME/.config/secrets/PAT")"
    export GH_TOKEN
fi

if ! gh auth status >/dev/null 2>&1; then
    echo "GitHub authentication not found, and no usable token at ~/.config/secrets/PAT." >&2
    echo "Run 'gh auth login' manually, or place a valid token in that file." >&2
    exit 1
fi

export -f sync_repo clone_repo

declare -A seen_repos=()
declare -a repos=()

add_repo_entry() {
    local entry="$1"

    if [[ -z "$entry" ]]; then
        return 0
    fi

    if [[ -z "${seen_repos[$entry]+x}" ]]; then
        repos+=("$entry")
        seen_repos["$entry"]=1
    fi
}

load_repo_group() {
    local group="$1"
    local group_file="$REPO_LIST_DIR/${group}.list"
    local line

    if [[ ! -f "$group_file" ]]; then
        echo "repo group not found: $group_file"
        return 0
    fi

    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        add_repo_entry "$line"
    done < "$group_file"
}

load_repo_list_file() {
    local list_file="$1"
    local line

    [[ -f "$list_file" ]] || return 0

    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        add_repo_entry "$line"
    done < "$list_file"
}

IFS=',' read -r -a selected_groups <<< "$SYNC_REPO_GROUPS"
for group in "${selected_groups[@]}"; do
    group="${group//[[:space:]]/}"
    [[ -z "$group" ]] && continue
    load_repo_group "$group"
done

load_repo_list_file "${LOCAL_REPO_LIST:-$REPO_LIST_DIR/local.list}"

declare -a sync_pids=()
for item in "${repos[@]}"; do
    if [[ "$item" != *";"* ]]; then
        echo "invalid repo entry (missing ';'): $item"
        continue
    fi

    dir="${item%%;*}"
    url="${item##*;}"

    dir="${dir/#\~/$HOME}"
    dir="${dir//\$HOME/$HOME}"

    sync_repo "$dir" "$url" &
    sync_pids+=("$!")
done

failed=0
for pid in "${sync_pids[@]}"; do
    wait "$pid" || failed=1
done

if [[ "$failed" -ne 0 ]]; then
    echo "one or more repositories could not be synchronized; see messages above" >&2
fi

# A single persistent repository conflict must not block unrelated updates or
# cause the login service to retry indefinitely. Per-repository errors are
# already logged by sync_repo.
exit 0
