{
  config,
  pkgs,
  lib,
  ...
}:

let
  # Host key of the Forgejo SSH server on omega (system/hosts/omega/forgejo.nix).
  # Forgejo generates it on first start, at /var/lib/forgejo/data/ssh/gitea.rsa,
  # so it changes only if that directory is lost; re-copy the .pub here then.
  forgeHostKeyPath = ./../../keys/forge_host_rsa.pub;
in
{
  options = {
    git.enable = lib.mkEnableOption "enables git";
  };

  config = lib.mkIf config.git.enable {

    environment.systemPackages = with pkgs; [
      git
      gh
      lazygit
    ];

    # Pinned rather than trust-on-first-use: the hourly wallpaper-sync timer
    # runs non-interactively, so an unknown host key would not prompt, it would
    # just fail every fetch with "Host key verification failed".
    programs.ssh.knownHosts.forge = lib.mkIf (builtins.pathExists forgeHostKeyPath) {
      hostNames = [ "[omega.tail29bd65.ts.net]:2222" ];
      publicKeyFile = forgeHostKeyPath;
    };

  };
}
