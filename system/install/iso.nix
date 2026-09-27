# Live installation environment. Secrets and tailnet identity are acquired at
# runtime by the installer, never copied into the image or the Nix store.
{ ... }:
{
  services.tailscale.enable = true;
  services.tailscale.extraDaemonFlags = [ "--state=mem:" ];

  services.getty.helpLine = ''
    Connect to the network with nmtui, then run:

      sudo nixos-config-install

    The installer joins the tailnet temporarily before building the new system.
  '';
}
