# Machine roster.
#
# Every machine this configuration is deployed to is listed here, and every
# machine builds `homeConfigurations.<name>`. Nothing about a machine lives in
# an untracked file any more.
#
# The roster key is both the NixOS hostname and the Tailscale node name.
{
  pc = {
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
  };

  alpha = {
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
  };

  omega = {
    system = "x86_64-linux";
    description = "Headless desktop server.";
    services = [
      {
        unit = "docker.service";
        label = "Container runtime";
      }
    ];
  };

  legion = {
    system = "x86_64-linux";
    description = "Laptop with the full desktop.";
    services = [
      {
        unit = "docker.service";
        label = "Container runtime";
      }
    ];
  };

  mac = {
    system = "aarch64-linux";
    description = "Apple Silicon laptop running Asahi, with the full desktop.";
    services = [
      {
        unit = "tailscale-advertise-routes.service";
        label = "Office network gateway";
      }
    ];
  };

  t480s = {
    system = "x86_64-linux";
    description = "ThinkPad T480s with the full desktop.";
    services = [ ];
  };

  t470 = {
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
  };

  zombie = {
    system = "x86_64-linux";
    description = "Headless laptop.";
    services = [ ];
  };
}
