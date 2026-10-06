{
  config,
  lib,
  pkgs,
  ...
}:
let
  # Private repo cloned here by repo-sync; layout documented in its README.md.
  secrets = "${config.home.homeDirectory}/.config/secrets";
  envFile = "${secrets}/api_keys/env_vars";
  # Single-line key files exported under the name their SDKs read.
  keyFiles = {
    TYPESAFE_API_KEY = "${secrets}/api_keys/typesafe";
  };
in
{
  # Source secrets only at shell runtime. Nix must never read these files
  # because evaluated contents would be copied into the world-readable
  # /nix/store.
  programs.bash.initExtra = ''
    if [ -r "${envFile}" ]; then
      set -a
      source "${envFile}"
      set +a
    fi
  ''
  + lib.concatStrings (
    lib.mapAttrsToList (name: file: ''
      if [ -z "''${${name}:-}" ] && [ -r "${file}" ]; then
        export ${name}="$(< "${file}")"
      fi
    '') keyFiles
  );

  # Git does not keep file modes, so a fresh clone or pull leaves secrets
  # world-readable. Owner-only everywhere except public keys. (ssh/ has its
  # own pass in features/ssh, which OpenSSH needs before this one matters.)
  home.activation.secretPermissions = lib.hm.dag.entryAfter [ "writeBoundary" ] ''
    if [ -d "${secrets}" ]; then
      ${pkgs.findutils}/bin/find "${secrets}" -path "${secrets}/.git" -prune -o \
        -type d -exec ${pkgs.coreutils}/bin/chmod 700 {} + 2>/dev/null || true
      ${pkgs.findutils}/bin/find "${secrets}" -path "${secrets}/.git" -prune -o \
        -type f ! -name '*.pub' ! -name README.md -exec ${pkgs.coreutils}/bin/chmod 600 {} + 2>/dev/null || true
    fi
  '';
}
