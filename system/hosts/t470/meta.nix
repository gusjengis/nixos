# Roster entry for this machine. See system/hosts/default.nix.
{
  system = "x86_64-linux";
  description = "ThinkPad T470, headless.";
  services = [
    {
      unit = "podman-homeassistant.service";
      label = "Home Assistant";
    }
    {
      unit = "musicassistant.service";
      label = "Music Assistant";
    }
    {
      unit = "podman-ble-scale-sync.service";
      label = "BLE scale sync";
    }
    {
      unit = "podman-zone-configurator.service";
      label = "Zone configurator";
    }
    {
      unit = "joshs-mass.service";
      label = "Josh's Music Assistant";
    }
  ];
}
