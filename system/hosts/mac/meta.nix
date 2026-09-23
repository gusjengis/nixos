# Roster entry for this machine. See system/hosts/default.nix.
{
  system = "aarch64-linux";
  description = "Apple Silicon laptop running Asahi, with the full desktop.";
  services = [
    {
      unit = "tailscale-advertise-routes.service";
      label = "Office network gateway";
    }
  ];
}
