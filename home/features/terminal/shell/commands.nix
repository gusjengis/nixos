{
  pkgs,
  lib,
  hosts,
  repoRoot,
  ...
}:
let
  hostNames = lib.concatStringsSep " " (builtins.attrNames hosts);

  resolveHost = ''
    if [ "$#" -gt 0 ] && [ "''${1#-}" = "$1" ]; then
      host="$1"
      shift
    fi

    if [ -z "$host" ]; then
      current_host=$(hostname)
      for known_host in ${hostNames}; do
        if [ "$current_host" = "$known_host" ]; then
          host="$current_host"
          break
        fi
      done
    fi

    if [ -z "$host" ]; then
      echo "$command_name: hostname does not match the fleet roster." >&2
      echo "        hostname: ''${current_host:-unknown}" >&2

      # Tailscale knows the name you gave this machine in the dashboard. It is
      # only ever a hint here: it needs the daemon and the control plane, so it
      # must not decide what a machine builds.
      if command -v tailscale >/dev/null 2>&1; then
        suggestion=$(tailscale status --json 2>/dev/null \
          | sed -n 's/.*"DNSName": *"\([^.]*\)\..*/\1/p' | head -1) || true
        [ -n "$suggestion" ] && echo "        tailscale calls it \"$suggestion\"." >&2
      fi

      echo "        Known hosts: ${hostNames}" >&2
      echo "        Run '$command_name <host>' to select one explicitly." >&2
      exit 1
    fi
  '';

  rebuildCmd = pkgs.writeShellApplication {
    name = "rebuild";
    text = ''
      repo=${repoRoot}
      command_name="rebuild"
      host="''${NIXOS_HOST:-''${HM_HOST:-}}"
      ${resolveHost}

      echo "rebuild: building $host"
      exec /run/wrappers/bin/sudo /run/current-system/sw/bin/nixos-rebuild switch \
        --flake "$repo#$host" "$@"
    '';
  };

  rehomeCmd = pkgs.writeShellApplication {
    name = "rehome";
    text = ''
      # The NixOS hostname normally selects the configuration. Pass a name
      # explicitly to override it during installation or recovery.
      repo=${repoRoot}
      command_name="rehome"
      host="''${HM_HOST:-}"
      ${resolveHost}

      echo "rehome: building $host"
      exec home-manager switch --flake "$repo#$host" "$@"
    '';
  };
in
{
  home.packages = [
    rebuildCmd
    rehomeCmd
  ];
}
