{
  inputs,
  lib,
  system,
  ...
}:

{
  imports = lib.optionals (system == "aarch64-linux") [
    inputs.apple-silicon.nixosModules.default
  ];
}
