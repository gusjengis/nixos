{
  config,
  lib,
  pkgs,
  inputs,
  ...
}:

{
  home.packages = lib.optionals config.dev.enable [
    inputs.claude-code-nix.packages.${pkgs.stdenv.hostPlatform.system}.claude-code
  ];
}
