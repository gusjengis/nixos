{ ... }:

{
  services.nfs.server = {
    enable = true;
    # NFSv4 only; v3 would need rpcbind/mountd and extra ports.
    # all_squash maps every client to gusjengis:users, keeping ownership
    # uniform regardless of which machine wrote a file.
    exports = ''
      /data 100.64.0.0/10(rw,no_subtree_check,all_squash,anonuid=1000,anongid=100)
    '';
  };

  services.nfs.settings.nfsd = {
    vers3 = false;
    vers4 = true;
    "vers4.0" = false;
    "vers4.1" = true;
    "vers4.2" = true;
  };

  # Only reachable over Tailscale, invisible to LAN and internet.
  networking.firewall.interfaces."tailscale0".allowedTCPPorts = [ 2049 ];
}
