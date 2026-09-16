# Helvetica Neue LT Std, vendored because it is not redistributable through
# nixpkgs. The OTFs live in ./fonts and are installed verbatim.
{ stdenvNoCC }:

stdenvNoCC.mkDerivation {
  pname = "helvetica-neue-lt-std";
  version = "2014.08.16";
  src = ./fonts;

  dontUnpack = true;

  installPhase = ''
    install -Dm644 "$src"/*.otf -t $out/share/fonts/opentype
  '';
}
