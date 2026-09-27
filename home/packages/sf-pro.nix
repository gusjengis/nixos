# Apple's SF Pro typeface, fetched straight from Apple's design resources.
#
# Lives here rather than beside a single consumer because two features need it:
# the Quickshell bar (QML `Theme.fontFamily`) and GTK theming (Thunar and every
# other GTK app). Keeping one derivation keeps both on the same font files.
{
  lib,
  stdenvNoCC,
  fetchurl,
  libarchive,
  p7zip,
}:

stdenvNoCC.mkDerivation {
  pname = "sf-pro";
  version = "2026-09-11";

  src = fetchurl {
    url = "https://devimages-cdn.apple.com/design/resources/download/SF-Pro.dmg";
    hash = "sha256-loqzuLH5LC2K9h6waA9cIiTE541ZuYa/AEUCp/wBKRg=";
  };

  nativeBuildInputs = [
    libarchive
    p7zip
  ];

  unpackPhase = ''
    runHook preUnpack
    7z x -y "$src"
    bsdtar -xf Payload~
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall
    install -Dm644 Library/Fonts/* -t "$out/share/fonts/opentype"
    runHook postInstall
  '';

  meta = {
    description = "Apple SF Pro typeface";
    homepage = "https://developer.apple.com/fonts/";
    license = lib.licenses.unfree;
    platforms = lib.platforms.all;
  };
}
