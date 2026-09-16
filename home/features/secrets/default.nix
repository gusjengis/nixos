{ config, ... }:
let
  envFile = "${config.home.homeDirectory}/.config/secrets/api_keys/env_vars";
in
{
  # Source secrets only at shell runtime. Nix must never read this file because
  # evaluated contents would be copied into the world-readable /nix/store.
  programs.bash.initExtra = ''
    if [ -r "${envFile}" ]; then
      set -a
      source "${envFile}"
      set +a
    fi
  '';
}
