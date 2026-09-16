{
  config,
  lib,
  ...
}:

{
  options.bambu.enable = lib.mkEnableOption "Bambu Studio flatpak" // {
    default = false;
  };

  config = lib.mkIf (config.bambu.enable && config.desktopEnv.enable) {
    services.flatpak = {
      enable = true;

      remotes = [
        {
          name = "flathub";
          location = "https://flathub.org/repo/flathub.flatpakrepo";
        }
      ];

      packages = [
        "com.bambulab.BambuStudio"
      ];
    };
  };
}
