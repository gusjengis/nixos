{
  config,
  lib,
  pkgs,
  ...
}:

{
  options.gaming.enable = lib.mkEnableOption "gaming" // {
    default = false;
  };
  config = lib.mkIf (config.gaming.enable && config.desktopEnv.enable) {
    home.packages = with pkgs; [
      prismlauncher
      atlauncher
      solitaire-tui
      (writeShellApplication {
        name = "steam";
        text = ''
          # Steam-generated desktop files use `steam steam://rungameid/...`.
          # Apply this policy at the command boundary, including future games.
          ${builtins.readFile ./steam-launch.sh}
          exec ${lib.getExe pkgs.steam} "''${steam_args[@]}"
        '';
      })
    ];
  };
}
