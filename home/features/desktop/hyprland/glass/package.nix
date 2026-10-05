{ pkgs, hyprland }:

pkgs.hyprlandPlugins.mkHyprlandPlugin {
  pluginName = "hyprglass";
  version = "0.9.1-macglass-experimental";
  inherit hyprland;
  src = pkgs.fetchFromGitHub {
    owner = "hyprnux";
    repo = "hyprglass";
    rev = "a54e7cd0232ca62a394aebebd553358dc6592652";
    sha256 = "1y42bf4hfqkllma2ci2l75plxmwi8hwgwd80f0gxmmd1qqcyybgr";
  };
  patches = [ ./experimental.patch ./hdr-encoding.patch ./linear-shadow.patch ./refraction.patch ./launcher-shape.patch ./config-lifecycle.patch ./layer-shadow.patch ./surface-material.patch ];
  nativeBuildInputs = [ pkgs.wayland-scanner ];
  makeFlags = [ "HYPRGLASS_VERSION=0.9.1-macglass-experimental" ];
  enableParallelBuilding = true;
  installPhase = ''
    runHook preInstall
    install -Dm755 hyprglass.so $out/lib/libhyprglass.so
    install -Dm644 LICENSE $out/share/licenses/hyprglass/LICENSE
    runHook postInstall
  '';
  meta.description = "Experimental macOS-fitted glass for matching Hyprland fork";
  meta.license = pkgs.lib.licenses.bsd3;
}
