# Roster entry for this machine. See system/hosts/default.nix.
{
  system = "x86_64-linux";
  description = "Main desktop. Gaming, game development, 3D printing, Windows VM host.";
  services = [
    {
      unit = "libvirtd.service";
      label = "Windows VM host";
    }
    {
      unit = "docker.service";
      label = "Container runtime";
    }
  ];
}
