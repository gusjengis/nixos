{ pkgs, hyprland }:

pkgs.hyprlandPlugins.mkHyprlandPlugin {
  pluginName = "hyprglass";
  version = "0.10.3-dock-ink";
  inherit hyprland;
  src = pkgs.fetchFromGitHub {
    owner = "hyprnux";
    repo = "hyprglass";
    rev = "a54e7cd0232ca62a394aebebd553358dc6592652";
    sha256 = "1y42bf4hfqkllma2ci2l75plxmwi8hwgwd80f0gxmmd1qqcyybgr";
  };
  patches = [
    ./experimental.patch
    ./hdr-encoding.patch
    ./linear-shadow.patch
    ./refraction.patch
    ./launcher-shape.patch
    ./config-lifecycle.patch
    ./layer-shadow.patch
    ./surface-material.patch
    ./portable-backend.patch
    ./apple-glass.patch
    ./dock-material.patch
    ./apple-layer.patch
    ./apple-system-presets.patch
    ./apple-toolbar.patch
    ./capture-target.patch
    ./shared-tint.patch
    ./dock-tooltip.patch
    ./hdr-mirror.patch
    ./desktop-affinity.patch
    ./dock-menu.patch
    ./dock-ink-regions.patch
  ];
  postPatch = ''
    cp ${./AppleSystemPresets.inc} src/AppleSystemPresets.inc
    cp ${./DesktopTintMath.hpp} src/DesktopTintMath.hpp
    cp ${./DesktopTint.inc} src/DesktopTint.inc
    cp ${./DesktopTintConfig.inc} src/DesktopTintConfig.inc
  '';
  nativeBuildInputs = [ pkgs.wayland-scanner ];
  makeFlags = [ "HYPRGLASS_VERSION=0.10.3-dock-ink" ];
  enableParallelBuilding = true;
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    $CC -Wall -Wextra -I./src -I./src/item-helper \
      ${./toolbar-protocol-test.c} ./src/item-helper/hyprglass-item-v1-protocol.c \
      $(pkg-config --cflags --libs wayland-server) -o toolbar-protocol-test
    ./toolbar-protocol-test
    $CXX -std=c++23 -Wall -Wextra -I./src ${./test-desktop-affinity.cpp} -o desktop-affinity-test
    ./desktop-affinity-test
    runHook postCheck
  '';
  installPhase = ''
    runHook preInstall
    install -Dm755 hyprglass.so $out/lib/libhyprglass.so
    install -Dm644 LICENSE $out/share/licenses/hyprglass/LICENSE
    runHook postInstall
  '';
  meta.description = "Experimental macOS-fitted glass for matching Hyprland fork";
  meta.license = pkgs.lib.licenses.bsd3;
}
