{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./ble_scale_sync.nix
    ./home_assistant.nix
    ./joshs_mass.nix
    ./music_assistant.nix
    ./zone_configurator.nix
  ];

  system.stateVersion = "25.11";
  git.enable = true;
  grub.enable = true;
  hyprland.enable = false;
  nvidia.enable = false;
  nvim.enable = true;
  tailscale.enable = true;
  homeAssistant.enable = true;
  zoneConfigurator.enable = true;
  musicAssistant.enable = true;
  joshsMass.enable = true;

  bleScaleSync = {
    enable = true;
    mqtt = {
      enable = true;
      deviceName = "Fit Plus Scale";
    };
    settings = {
      ble = {
        adapter = "hci0";
        scale_mac = "FF:06:00:00:CC:FB";
      };
      runtime = {
        dry_run = false;
        debug = false;
      };
      scale.weight_unit = "lbs";
      users = [
        {
          name = "Anthony";
          slug = "anthony";
          height = 188;
          birth_date = "2003-02-17";
          gender = "male";
          is_athlete = false;
          weight_range = {
            min = 30;
            max = 250;
          };
        }
      ];
    };
  };
}
