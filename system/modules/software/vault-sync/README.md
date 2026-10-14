# Vault Sync

One NixOS module syncs `~/Documents/Obsidian` as one folder, including every
current and future vault beneath it. Hosts in
`vaultSync.deviceIds` participate by default; override the input to change the
roster or set `vaultSync.enable = false` to opt out. No host-specific copies of
the folder configuration are needed.

- `~/Documents/Obsidian/Notes`: existing capture and processing vault.
- `~/Documents/Obsidian/vault`: manual writing, created without Obsidian setup.
  Git is initialized separately on each host; `.git` never syncs. Use a Git
  remote to share commits, not Syncthing.
- New vaults and other files beneath `~/Documents/Obsidian` sync automatically;
  no folder-specific Nix configuration is required.
- Git metadata and Obsidian workspace files are excluded at every depth.
  Nested `.stfolder`, `.stignore`, and `.stversions` from old shares stay local.
  Only the root `.stignore` controls this share.
- `omega` stays online and retains incoming replaced/deleted files for up to
  30 days. Its own edits are not covered by Syncthing versioning.
- Peers connect using Tailscale host names on TCP 22000. No public discovery,
  relay, or router port mapping is used. GUI listens on localhost port 8384.

## Enrollment

Generate a unique identity on each host with:

```sh
umask 077
syncthing generate --home="$HOME/.config/syncthing"
```

Record its public device ID in `devices.nix` (or the `vaultSync.deviceIds`
input), commit the configuration, and rebuild participating hosts. Private
`key.pem` stays local and must not enter the Nix store or configuration Git.
Preserve `cert.pem` and `key.pem` through reinstalls. Missing identity files
cause the service to stay inactive rather than silently change device ID.

Stop every existing Obsidian Sync service before starting Syncthing on Notes;
keep the Obsidian Sync core plugin disabled. Run `rehome` to remove the old
desktop unit and rebuild NixOS for the new system service. Never run two sync
engines against the same folder. Offline hosts need enrollment/deployment when
they return, not concurrent operation of old and new services.

Initial enrollment merges existing copies rather than deleting differences.
Syncthing cannot recover the old sync engine's deletion history, so stale
copies can reintroduce previously deleted files. Review conflicts and unexpected
notes after joining an old replica; this migration deliberately preserves data.

## Migration Backup

When replacing the old `obsidian-notes` and `obsidian-vault` shares, remove
those folder configurations on every reachable peer before enabling the
`obsidian-root` share. Removing a Syncthing folder configuration does not
delete its files. Do not run parent and child shares concurrently. Install
root ignore patterns before the first scan; leave old version archives intact.
An offline peer must retire its old shares before adopting the root share.

One pre-cutover backup was made on omega at
`~/Backups/Notes-20261013T050137Z.tar.gz` (SHA-256
`21c97ea5400c3b51c1fe1919d3c005862075c79201bf0d7c21e42383bf37468e`).
Processing remained running; archive integrity passed, but this is not an
atomic filesystem snapshot or an ongoing backup service.

For rollback, stop Syncthing on every participating host before restoring
files or restarting Obsidian Sync. Restore the old Nix configuration only
after the new sync engine is stopped. Do not delete either remote vault or
the migration backup as part of cutover.
