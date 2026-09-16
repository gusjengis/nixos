{
  config,
  pkgs,
  lib,
  repoRoot,
  ...
}:
let
  configRoot = "${repoRoot}/home/features/ssh";
in
{
  home.packages = [ pkgs.openssh ];

  home.file = {
    ".ssh/config".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/config";
    ".ssh/authorized_keys".source = config.lib.file.mkOutOfStoreSymlink "${configRoot}/authorized_keys";
  };

  # Old generations linked these paths into the deleted config_files tree.
  # Remove only dangling symlinks before Home Manager checks link targets;
  # never replace a real file or a valid link here.
  home.activation.sshMigrateDanglingLinks = lib.hm.dag.entryBefore [ "checkLinkTargets" ] ''
    for target in "$HOME/.ssh/config" "$HOME/.ssh/authorized_keys"; do
      if [[ -L "$target" && ! -e "$target" ]]; then
        rm "$target"
      fi
    done
  '';

  # Synced private keys may arrive as 0644 because Git does not preserve
  # arbitrary regular-file modes. OpenSSH refuses to use them until corrected.
  home.activation.sshSecretPermissions = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    secrets_dir="${config.home.homeDirectory}/.config/secrets"
    ssh_secrets="$secrets_dir/ssh"

    if [ -d "$ssh_secrets" ]; then
      ${pkgs.coreutils}/bin/chmod 700 "$secrets_dir" "$ssh_secrets" 2>/dev/null || true

      for file in "$ssh_secrets"/*; do
        [ -f "$file" ] || continue
        case "$file" in
          *.pub) ${pkgs.coreutils}/bin/chmod 644 "$file" 2>/dev/null || true ;;
          *) ${pkgs.coreutils}/bin/chmod 600 "$file" 2>/dev/null || true ;;
        esac
      done
    fi
  '';

  # These pre-existing links remain intentionally unmanaged. Both point at
  # missing files; their original purpose is unknown. The second targets the
  # deleted config_files/ tree, so it can never resolve again:
  #   ~/.ssh/id_ed25519     -> ~/.config/secrets/ssh/id_ed25519
  #   ~/.ssh/id_ed25519.pub -> /etc/nixos/home/features/ssh/id_ed25519.pub
}
