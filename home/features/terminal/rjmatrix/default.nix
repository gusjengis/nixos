{
  config,
  pkgs,
  inputs,
  lib,
  ...
}:
let
  rjmatrix = pkgs.rustPlatform.buildRustPackage {
    pname = "rjmatrix";
    version = "1.0.7";
    src = inputs.rmatrix.outPath;
    cargoLock.lockFile = "${inputs.rmatrix.outPath}/Cargo.lock";
  };
in
{
  config = lib.mkIf config.desktopEnv.enable {
    home.packages = [ rjmatrix ];

    programs.bash.shellAliases.matrix = "rjmatrix";
  };
}
