{
  pkgs,
  lib,
  hosts,
  hostName,
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
      host=${lib.escapeShellArg hostName}
      host="''${HM_HOST:-$host}"
      host="''${NIXOS_HOST:-$host}"
      ${resolveHost}

      echo "rebuild: building $host"
      exec /run/wrappers/bin/sudo /run/current-system/sw/bin/nixos-rebuild switch \
        --flake "$repo#$host" "$@"
    '';
  };

  rehomeCmd = pkgs.writeShellApplication {
    name = "rehome";
    text = ''
      # The installed Home Manager configuration identifies this machine even
      # when the runtime hostname is stale during installation or recovery.
      repo=${repoRoot}
      command_name="rehome"
      host="''${HM_HOST:-${lib.escapeShellArg hostName}}"
      ${resolveHost}

      echo "rehome: building $host"
      exec home-manager switch --flake "$repo#$host" "$@"
    '';
  };

  refreshHardwareCmd = pkgs.writeShellApplication {
    name = "refresh-hardware";
    runtimeInputs = [ pkgs.git ];
    text = ''
      # Re-probes this machine's hardware with nixos-facter and overwrites its
      # committed report. Run this after any hardware change (new GPU, added
      # or removed drive, dock/undock on a laptop, etc.) -- nothing does this
      # automatically, since a rebuild only re-evaluates whatever report is
      # already committed. This does not stage or commit the change; review
      # the diff, then commit and rebuild yourself.
      repo=${repoRoot}
      command_name="refresh-hardware"
      host=${lib.escapeShellArg hostName}
      host="''${HM_HOST:-$host}"
      host="''${NIXOS_HOST:-$host}"
      ${resolveHost}

      target="$repo/system/hosts/$host/facter.json"
      if [ ! -d "$(dirname "$target")" ]; then
        echo "$command_name: $(dirname "$target") does not exist yet." >&2
        exit 1
      fi

      # nixos-facter runs as root and refuses to write to a file that already
      # exists with different ownership, so the path must not be pre-created
      # (no mktemp): let it create the file itself.
      tmp="''${TMPDIR:-/tmp}/$command_name-$host-$$.json"
      trap '/run/wrappers/bin/sudo /run/current-system/sw/bin/rm -f "$tmp"' EXIT

      echo "$command_name: probing hardware for $host (needs sudo)"
      /run/wrappers/bin/sudo /run/current-system/sw/bin/nix run nixpkgs#nixos-facter -- -o "$tmp"
      /run/wrappers/bin/sudo /run/current-system/sw/bin/chmod 644 "$tmp"

      cp "$tmp" "$target"
      echo "$command_name: wrote $target"

      # git diff ignores untracked files entirely, so a brand-new host's
      # first report needs its own case instead of just diffing.
      status="$(git -C "$repo" status --porcelain -- "$target")"
      case "$status" in
        "")
          echo "$command_name: no changes detected."
          ;;
        '??'*)
          echo "$command_name: $target is new to git."
          echo "$command_name: review it, then 'git add' it before committing."
          ;;
        *)
          echo "$command_name: review before rebuilding:"
          git -C "$repo" diff --stat -- "$target"
          echo "$command_name: run 'git -C $repo diff -- $target' for details, then 'rebuild'."
          ;;
      esac
    '';
  };
in
{
  home.packages = [
    rebuildCmd
    rehomeCmd
    refreshHardwareCmd
  ];
}
