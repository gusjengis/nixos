#!/usr/bin/env bash
# Runs headless Obsidian Sync for one vault, logging in and linking the vault
# first when this machine has not done so yet. Credentials come from the
# secrets repo so no machine needs an interactive `ob login`.
#
# Environment (set by the Nix wrapper):
#   OBSIDIAN_CREDENTIALS  file: line 1 email, line 2 password
#   OBSIDIAN_VAULT        local vault path
#   OBSIDIAN_REMOTE_VAULT remote vault ID or name
set -euo pipefail

credentials="$OBSIDIAN_CREDENTIALS"
vault="$OBSIDIAN_VAULT"
remote="$OBSIDIAN_REMOTE_VAULT"
token="${XDG_CONFIG_HOME:-$HOME/.config}/obsidian-headless/auth_token"

login() {
	local email
	email="$(sed -n 1p "$credentials")"
	# The password goes through stdin (ob reads prompts from a non-TTY stdin
	# until EOF) so it never appears in the process list.
	sed -n 2p "$credentials" | ob login --email "$email" >/dev/null
	echo "Logged in to Obsidian"
}

if [ ! -s "$token" ]; then
	login
elif ! ob sync-list-remote --json >/dev/null 2>&1; then
	# Token revoked or expired; `ob login` with credentials replaces it.
	echo "Stored Obsidian token rejected; logging in again"
	login
fi

mkdir -p "$vault"
if ! ob sync-list-local --json | grep -qF "\"$vault\""; then
	# Standard-encryption vaults need no password here. An end-to-end
	# encrypted vault would fail this step with "Password not provided."
	ob sync-setup --json \
		--vault "$remote" \
		--path "$vault" \
		--device-name "$(hostname)" >/dev/null
	echo "Linked $vault to remote vault $remote"
fi

exec ob sync --continuous --path "$vault"
