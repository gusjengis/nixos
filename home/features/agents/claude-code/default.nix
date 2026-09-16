{ pkgs, inputs, ... }:

{
  home.packages = [
    inputs.claude-code-nix.packages.${pkgs.stdenv.hostPlatform.system}.claude-code
  ];
}
