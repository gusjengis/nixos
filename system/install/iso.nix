# Live installation environment. Secrets and tailnet identity are acquired at
# runtime by the installer, never copied into the image or the Nix store.
{ ... }:
{
  services.tailscale.enable = true;
  services.tailscale.extraDaemonFlags = [ "--state=mem:" ];

  # Bash expands the word after a trailing-space alias. Keep coreutils' install
  # in PATH for nixos-enter and other noninteractive installation scripts.
  environment.shellAliases = {
    sudo = "sudo ";
    install = "nixos-config-install";
  };

  services.getty.helpLine = ''
    Connect to the network with nmtui, then run:

      sudo install

    The installer joins the tailnet temporarily before building the new system.
  '';
}
