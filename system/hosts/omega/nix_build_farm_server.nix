# Omega-specific build server and signed binary cache.
{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nixBuildFarm;
  signKeyPath = "/var/lib/nix-cache/cache-priv-key.pem";
  keyName = "omega-1";
  coresPerJob = 6;
  minFreeGiB = 50;
  maxFreeGiB = 200;
  retentionDays = 30;

  # Public half is shared with login access; private half remains outside store.
  sharedKeyPath = ./../../keys/shared_ed25519.pub;
in
{
  assertions = [
    {
      assertion = config.tailscale.enable;
      message = "Omega's build farm must be reachable over Tailscale.";
    }
  ];

  # Register foreign interpreters and advertise those platforms to clients.
  boot.binfmt.emulatedSystems = cfg.emulatedSystems;

  nix.settings = {
    max-jobs = cfg.maxJobs;
    cores = coresPerJob;
    trusted-users = [ cfg.sshUser ];
    secret-key-files = [ signKeyPath ];
    min-free = minFreeGiB * 1024 * 1024 * 1024;
    max-free = maxFreeGiB * 1024 * 1024 * 1024;
  };

  nix.gc = {
    automatic = true;
    dates = "monthly";
    options = "--delete-older-than ${toString retentionDays}d";
  };

  nix.optimise = {
    automatic = true;
    dates = [ "weekly" ];
  };

  users.groups.${cfg.sshUser} = { };
  users.users.${cfg.sshUser} = {
    isSystemUser = true;
    group = cfg.sshUser;
    home = "/var/lib/${cfg.sshUser}";
    createHome = true;
    shell = pkgs.bashInteractive;
    openssh.authorizedKeys.keys = lib.optionals (builtins.pathExists sharedKeyPath) [
      (lib.strings.removeSuffix "\n" (builtins.readFile sharedKeyPath))
    ];
  };

  # Generate missing key, then reject mismatch before Harmonia can serve paths
  # carrying signatures clients will not trust.
  systemd.services.nix-cache-key = {
    description = "Nix binary cache signing key";
    wantedBy = [ "multi-user.target" ];
    before = [
      "harmonia.service"
      "nix-daemon.service"
    ];
    requiredBy = [ "harmonia.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      key=${lib.escapeShellArg signKeyPath}

      install -d -m 0755 -o root -g root "$(dirname "$key")"

      if [ ! -f "$key" ]; then
        echo "no signing key at $key; generating one"
        ${pkgs.nix}/bin/nix-store --generate-binary-cache-key \
          ${lib.escapeShellArg keyName} "$key" "$key.pub"
        chmod 0400 "$key"
        chmod 0444 "$key.pub"
      fi

      actual="$(${pkgs.nix}/bin/nix key convert-secret-to-public < "$key")"
      expected=${lib.escapeShellArg cfg.publicKey}

      if [ "$actual" != "$expected" ]; then
        echo "signing key at $key does not match nixBuildFarm.publicKey." >&2
        echo "  on disk:    $actual" >&2
        echo "  configured: $expected" >&2
        echo "Either restore the original private key from backup, or set" >&2
        echo "nixBuildFarm.publicKey to the value above and rebuild every client." >&2
        exit 1
      fi
    '';
  };

  services.harmonia.cache = {
    enable = true;
    signKeyPaths = [ signKeyPath ];
    settings = {
      bind = "[::]:${toString cfg.port}";
      # cache.nixos.org uses 40; higher number gives this cache lower priority.
      priority = 50;
    };
  };

  networking.firewall.interfaces."tailscale0".allowedTCPPorts = [ cfg.port ];
}
