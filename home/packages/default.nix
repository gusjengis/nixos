# Packages built from this repository, exposed as an overlay so every module
# can reach them through `pkgs`.
final: prev: {
  helvetica-neue-lt-std = final.callPackage ./helvetica-neue-lt-std { };
}
