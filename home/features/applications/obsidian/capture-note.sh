#!/usr/bin/env bash
# Writes one captured thought as a new note in the vault's Raw/ folder.
#
# Usage: capture-note [TEXT]   (reads stdin when TEXT is omitted)
#
# Notes are left unfiled on purpose: `status: inbox` marks them for later
# labeling and placement, so nothing has to be decided at capture time.
set -euo pipefail

vault="${OBSIDIAN_VAULT:-$HOME/Documents/Obsidian/Notes}"
folder="$vault/Raw"
source="${CAPTURE_SOURCE:-dictation}"

if [ "$#" -gt 0 ]; then
	text="$1"
else
	text="$(cat)"
fi

# Nothing said, nothing saved.
if [ -z "${text//[[:space:]]/}" ]; then
	exit 0
fi

mkdir -p "$folder"

stamp="$(date +%Y-%m-%d-%H%M%S)"
created="$(date +%Y-%m-%dT%H:%M:%S)"

# Staged at the vault root under a dot name: Obsidian and headless sync both
# ignore root-level dotfiles, so a half-written note is never picked up.
tmp="$(mktemp "$vault/.capture.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

printf -- '---\ncreated: %s\nstatus: inbox\nsource: %s\n---\n%s\n' \
	"$created" "$source" "$text" >"$tmp"
chmod 644 "$tmp"

# `ln` refuses to overwrite, so two captures in the same second cannot clobber
# each other; the loser takes the next suffix.
name="$stamp"
suffix=1
until ln "$tmp" "$folder/$name.md" 2>/dev/null; do
	suffix=$((suffix + 1))
	name="$stamp-$suffix"
done

printf '%s\n' "$folder/$name.md"
