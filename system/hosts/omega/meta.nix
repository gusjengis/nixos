# Roster entry for this machine. See system/hosts/default.nix.
{
  system = "x86_64-linux";
  description = "Headless desktop server.";
  services = [
    {
      unit = "docker.service";
      label = "Container runtime";
    }
    {
      unit = "forgejo.service";
      label = "Private git forge";
    }
    {
      unit = "wallpaper-fetch.timer";
      label = "Nightly wallpaper collection";
    }
  ];
}
