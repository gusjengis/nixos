# Machine roster.
#
# Every machine this configuration is deployed to is listed here, and every
# machine builds `homeConfigurations.<name>`. Nothing about a machine lives in
# an untracked file any more.
#
# The roster key is both the NixOS hostname and the Tailscale node name.
#
# The roster is discovered rather than hand-written: every directory beside
# this file that contains a `meta.nix` is a machine. Adding a host is therefore
# creating a directory, which is what the installer does. Nothing has to edit a
# shared file, so two machines enrolled independently never conflict here.
#
# Each `meta.nix` evaluates to:
#
#   { system; description; services = [ { unit; label; } ]; systemManaged ? true; }
#
# `systemManaged = false` keeps a machine in the Home Manager roster without
# building a NixOS configuration for it.
let
  entries = builtins.readDir ./.;

  isHost = name: entries.${name} == "directory" && builtins.pathExists (./. + "/${name}/meta.nix");

  hostNames = builtins.filter isHost (builtins.attrNames entries);
in
builtins.listToAttrs (
  map (name: {
    inherit name;
    value = import (./. + "/${name}/meta.nix");
  }) hostNames
)
