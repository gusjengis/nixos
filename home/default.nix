# Everything every machine shares. Per-machine Home Manager settings live in
# home/hosts/<name>; the machine roster lives in system/hosts/default.nix.
{
  config,
  lib,
  pkgs,
  hostName,
  repoRoot,
  ...
}:

{
  imports = [
    ./features
    ./policy/insecure-packages.nix
    ./hosts/${hostName}
  ];

  options = {
    host.name = lib.mkOption {
      type = lib.types.str;
      readOnly = true;
      description = "Which entry of system/hosts this machine is building.";
    };

    desktopEnv.enable = lib.mkEnableOption "desktop environment packages" // {
      default = true;
    };

    dev.enable = lib.mkEnableOption "dev tools and repos" // {
      default = true;
    };

    laptop.enable = lib.mkEnableOption "is a laptop" // {
      default = true;
    };
  };

  config = lib.mkMerge [
    {
      host.name = hostName;

      programs.home-manager.enable = true;

      home.username = "gusjengis";
      home.homeDirectory = "/home/gusjengis";

      home.sessionVariables.NIXOS_CONFIG_ROOT = repoRoot;

      home.stateVersion = "25.05";

      fonts.fontconfig.enable = true;

      nixpkgs.config.allowUnfree = true;
    }

    (lib.mkIf config.desktopEnv.enable {
      home.sessionVariables = {
        LD_LIBRARY_PATH = /run/opengl-driver/lib;
      };
    })
  ];
}
