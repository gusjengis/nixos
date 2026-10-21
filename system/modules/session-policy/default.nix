{ inputs, system, ... }:
let
  pkgs = import inputs.nixpkgs-system { inherit system; };
  material = import ./materialize.nix { inherit pkgs; };
in
{
  imports = [ "${material}/module.nix" ];
  sessionSchedule = import ./schedule.nix;
}
