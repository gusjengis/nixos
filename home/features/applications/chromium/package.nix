{ pkgs }:

let
  # Unrelated repository edits must not invalidate an hours-long browser build.
  sourceFile = name: builtins.path { path = ./. + "/${name}"; inherit name; };
in
# Patch the browser derivation inside Chromium's scope, before the Widevine
# copy and launcher are constructed. Patching the outer package only changes
# the launcher and never rebuilds Chromium itself.
pkgs.chromium.override {
  enableWideVine = true;
  newScope = scope: pkgs.newScope (scope // {
    mkChromiumDerivation = build:
      (scope.mkChromiumDerivation build).overrideAttrs (old: {
        patches = (old.patches or [ ]) ++ [
          (sourceFile "macos-theme.patch")
          (sourceFile "quickshell-menu.patch")
          (sourceFile "page-context-menu.patch")
          (sourceFile "macos-titlecase.patch")
          (sourceFile "macos-native-provider.patch")
        ];
        postPatch = (old.postPatch or "") + ''
          cp ${sourceFile "menu_runner_impl_quickshell.h"} ui/views/controls/menu/menu_runner_impl_quickshell.h
          cp ${sourceFile "menu_runner_impl_quickshell.cc"} ui/views/controls/menu/menu_runner_impl_quickshell.cc
          cp ${sourceFile "native_chrome_color_mixer_macos_port.cc"} chrome/browser/ui/color/mac/native_chrome_color_mixer_mac.cc
          cp ${sourceFile "macos_palette.inc"} chrome/browser/ui/color/macos_palette.inc
        '';
        # Compile the bridge first so an API mismatch fails before the long
        # browser build, rather than near its end.
        preBuild = (old.preBuild or "") + ''
          ninja -C out/Release -j$NIX_BUILD_CORES obj/chrome/browser/ui/color/mixers/native_chrome_color_mixer_mac.o
          ninja -C out/Release -j$NIX_BUILD_CORES obj/ui/views/views/menu_runner_impl_quickshell.o
        '';
      });
  });
}
