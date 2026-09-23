# Roster entry for this machine. See system/hosts/default.nix.
{
  system = "x86_64-linux";
  description = "Laptop with the full desktop.";
  services = [
    {
      unit = "docker.service";
      label = "Container runtime";
    }
  ];
}
