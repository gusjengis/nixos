#!/usr/bin/env bash
set -euo pipefail

state_dir="${XDG_RUNTIME_DIR:-/run/user/$UID}/home-manager-notifications"
log_file="$state_dir/clone-repo.log"

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
    printf '%s\t%s\t%s\t%s\n' "$(date --iso-8601=seconds)" "$urgency" "${1:-clone-repo}" "${2:-}" >>"$log_file"
}

clone_repo() {
    local repo_url="$1"
    local repo_name

    repo_name=$(basename -s .git "$repo_url")

    if [ ! -d "$repo_name" ]; then
        # --recurse-submodules: .home-manager carries the Neovim config as a
        # submodule, and a clone without it deploys an empty config directory.
        git clone --recurse-submodules "$repo_url" 2>/dev/null || { echo "clone failed: $repo_url"; return 1; }
    else
        if ! git -C "$repo_name" rev-parse --git-dir >/dev/null 2>&1; then
            echo "$repo_name: not a valid git repository - removing and re-cloning"
            sudo rm -rf "$repo_name"
            sudo git clone "$repo_url" 2>/dev/null || { echo "clone failed: $repo_url"; return 1; }
            sudo chown -R "$USER":users "$repo_name"
            return 0
        fi

        (
            set +e
            cd "$repo_name" 2>/dev/null || { echo "cd failed: $repo_name"; return 0; }

            # --ignore-submodules=all: the Neovim config submodule sits on its
            # own branch and is routinely a commit or two away from the pin.
            # Counting that as "uncommitted changes" would stop .home-manager
            # from ever pulling again.
            if [ -n "$(git status --porcelain --ignore-submodules=all)" ]; then
                echo "$repo_name: uncommitted changes"
                return 0
            fi

            git fetch origin 2>/dev/null || { echo "fetch failed: $repo_name"; return 1; }

            local local_rev remote_rev
            local_rev=$(git rev-parse HEAD 2>/dev/null || echo "")
            remote_rev=$(git rev-parse "@{u}" 2>/dev/null || echo "")

            if [ -z "$remote_rev" ]; then
                echo "$repo_name: no upstream branch configured"
                return 1
            fi

            if [ "$local_rev" != "$remote_rev" ]; then
                git pull --ff-only -q 2>/dev/null || {
                    local pull_result=$?
                    if [ $pull_result -eq 128 ]; then
                        echo "$repo_name: conflict with upstream"
                    else
                        echo "$repo_name: pull failed"
                    fi
                    return 1
                }
            fi
        )
    fi
}

sync_repo() {
    local dir="$1"
    local repo_url="$2"
    local output
    local repo_name
    local status

    repo_name=$(basename -s .git "$repo_url")

    mkdir -p "$dir"

    if output=$(
        set -o pipefail
        (cd "$dir" 2>/dev/null && clone_repo "$repo_url") | sed 's/\x1b\[[0-9;]*m//g'
    ); then
        status=0
    else
        status=$?
    fi

    if [ -n "$output" ]; then
        description=$(echo "$output" | cut -d':' -f2- | sed 's/^ *//')
        notify --urgency=critical "$repo_name" "$description"
        echo -e "\033[31m$output\033[0m"
    fi

    return "$status"
}
