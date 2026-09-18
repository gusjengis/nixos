{
  pkgs,
  lib,
  hosts,
  repoRoot,
  ...
}:
let
  # "<machine-id> <host>" per line, baked in from system/hosts/default.nix so the
  # roster has exactly one source.
  machineIdTable = lib.concatMapStringsSep "\n" (name: "${hosts.${name}.machineId} ${name}") (
    builtins.attrNames hosts
  );

  hostNames = lib.concatStringsSep " " (builtins.attrNames hosts);

  resolveHost = ''
    if [ "$#" -gt 0 ] && [ "''${1#-}" = "$1" ]; then
      host="$1"
      shift
    fi

    if [ -z "$host" ]; then
      machine_id=""
      if [ -r /etc/machine-id ]; then
        machine_id=$(cat /etc/machine-id)
      fi

      # `if` rather than `&&`: under `set -e` a failing `&&` list as the last
      # command of the loop body would kill this subshell on the first line
      # that does not match.
      host=$(
        while read -r id name; do
          if [ "$id" = "$machine_id" ]; then
            echo "$name"
          fi
        done <<'MACHINE_IDS'
    ${machineIdTable}
    MACHINE_IDS
      )
    fi

    if [ -z "$host" ]; then
      echo "$command_name: this machine's id is not in system/hosts/default.nix." >&2
      echo "        machine-id: ''${machine_id:-unknown}" >&2

      # Tailscale knows the name you gave this machine in the dashboard. It is
      # only ever a hint here: it needs the daemon and the control plane, so it
      # must not decide what a machine builds.
      if command -v tailscale >/dev/null 2>&1; then
        suggestion=$(tailscale status --json 2>/dev/null \
          | sed -n 's/.*"DNSName": *"\([^.]*\)\..*/\1/p' | head -1) || true
        [ -n "$suggestion" ] && echo "        tailscale calls it \"$suggestion\"." >&2
      fi

      echo "        Known hosts: ${hostNames}" >&2
      echo "        Run '$command_name <host>', then record the machine-id in system/hosts/default.nix." >&2
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
      # Every one of these machines reports the hostname "nixos", so the
      # configuration is chosen by /etc/machine-id instead. That is unique per
      # install, readable offline, and needs no daemon. Pass a name explicitly
      # to override it, which is also what a fresh install needs before its new
      # machine-id has been recorded in system/hosts/default.nix.
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
