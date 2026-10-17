{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ inputs.strata.packages.${pkgs.stdenv.hostPlatform.system}.default ];
  };
}
