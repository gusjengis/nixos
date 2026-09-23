# Hardware-derived Home Manager defaults.
#
# Home Manager is standalone, so it cannot read the NixOS side's
# `repo.hardware.detected`. It reads the same committed Facter report directly
# instead, through the shared helper, so `laptop.enable` never has to be
# answered by a human during installation.
#
# These are `mkDefault`, so an explicit value in `home/hosts/<host>` still
# wins. Every currently rostered machine sets `laptop.enable` explicitly, which
# is why introducing this default changed none of their derivations.
{
  lib,
  hostName,
  ...
}:
let
  facter = import ../../system/install/lib/facter.nix { inherit lib; };
  portable = facter.isPortableHost ../../system/hosts hostName;
in
{
  config = {
    laptop.enable = lib.mkDefault portable;
  };
}
