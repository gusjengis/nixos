{
  lib,
  stdenv,
  fetchFromGitHub,
  fpc,
  lazarus,
  gtk3,
  makeDesktopItem,
  copyDesktopItems,
  wrapGAppsHook3,
  autoPatchelfHook,
}:

stdenv.mkDerivation {
  pname = "insta360-link-controller";
  version = "0-unstable-2026-11-05";

  src = fetchFromGitHub {
    owner = "vrwallace";
    repo = "Insta360-Link-1-and-2-Controller-for-Linux";
    rev = "650a529389388c3e09ed909e900e607dcbd1c977";
    hash = "sha256-ha7iR3BCpxTeaPhgPxCHveRbJhVznWiasRGiWWf/Zhc=";
  };

  nativeBuildInputs = [ fpc lazarus copyDesktopItems wrapGAppsHook3 autoPatchelfHook ];
  buildInputs = [ gtk3 ];

  buildPhase = ''
    runHook preBuild
    export HOME="$TMPDIR/home"
    mkdir -p "$HOME"
    lazbuild --primary-config-path="$TMPDIR/lazarus-config" \
      --lazarusdir=${lazarus}/share/lazarus \
      --build-mode=Release --widgetset=gtk3 insta360linkgui.lpi
    fpc -Mobjfpc -Sh -O2 linkctl.pas
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    install -Dm755 insta360linkgui "$out/bin/insta360linkgui"
    install -Dm755 linkctl "$out/bin/linkctl"
    runHook postInstall
  '';

  desktopItems = [
    (makeDesktopItem {
      name = "insta360-link-controller";
      desktopName = "Insta360 Link Controller";
      comment = "Configure Insta360 Link webcam, tracking, and camera presets";
      exec = "insta360linkgui";
      icon = "camera-web";
      categories = [ "AudioVideo" "Video" "Settings" ];
    })
  ];

  meta = {
    description = "Linux GUI and CLI controller for Insta360 Link webcams";
    homepage = "https://github.com/vrwallace/Insta360-Link-1-and-2-Controller-for-Linux";
    license = lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "insta360linkgui";
  };
}
