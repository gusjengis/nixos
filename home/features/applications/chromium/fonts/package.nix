{ pkgs }:
let
  sfPro = pkgs.callPackage ../../../../packages/sf-pro.nix { };
  python = pkgs.python3.withPackages (ps: [ ps.fonttools ]);
  prepare = builtins.path { path = ./prepare-ui-font.py; name = "prepare-ui-font.py"; };
in
pkgs.runCommand "chromium-ui-sf-pro-opsz17" { nativeBuildInputs = [ python ]; } ''
  mkdir -p "$out/share/fonts/truetype"
  python ${prepare} ${sfPro}/share/fonts/opentype "$out/share/fonts/truetype"
''
