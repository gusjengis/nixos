{ pkgs, hyprland }:

# This revision matches the fork's window-presentation API, before render contexts.
pkgs.hyprlandPlugins.mkHyprlandPlugin {
  pluginName = "borders-plus-plus";
  version = "2026-08-23";
  inherit hyprland;
  src = (pkgs.fetchzip {
    url = "https://github.com/hyprwm/hyprland-plugins/archive/2b41ad87ba68226472b8a811c3f580a1eabb10bb.tar.gz";
    hash = "sha256-QlwOFpistZmkBdIrCBya3ooLOIFL6E3zYRID5LmuNQ8=";
  }) + "/borders-plus-plus";
  patches = [ ./borders-animation-alpha.patch ];
  nativeBuildInputs = [ pkgs.cmake ];
  meta.license = pkgs.lib.licenses.bsd3;
}
