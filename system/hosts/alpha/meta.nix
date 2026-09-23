# Roster entry for this machine. See system/hosts/default.nix.
{
  system = "x86_64-linux";
  description = "Headless desktop server.";
  services = [
    {
      unit = "nfs-server.service";
      label = "Fleet data drive";
    }
    {
      unit = "immich-server.service";
      label = "Immich photo library";
    }
    {
      unit = "phpfpm-nextcloud.service";
      label = "Nextcloud";
    }
    {
      unit = "parakeet-asr.service";
      label = "GPU speech recognition";
    }
    {
      unit = "ultrabridge.service";
      label = "UltraBridge device sync";
    }
  ];
}
