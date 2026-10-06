import QtQuick
import Quickshell
import Quickshell.Wayland
import "../theme"

// Wallpaper treatment lives below app windows; only bar controls live above.
PanelWindow {
    id: scrim
    required property bool shown
    readonly property url fragment: "file://" + (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share") + "/quickshell/shaders/bar-scrim.frag.qsb"

    visible: shown && Theme.wallpaperPath !== ""
    implicitHeight: Theme.barScrimHeight
    // Match the wallpaper origin even when the bar reserves notch space.
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    WlrLayershell.namespace: "quickshell-bar-scrim"
    WlrLayershell.layer: WlrLayer.Bottom
    anchors { top: true; left: true; right: true }
    mask: Region {}

    Image {
        id: wallpaper
        width: scrim.width
        height: scrim.screen.height
        source: Theme.wallpaperPath === "" ? "" : "file://" + Theme.wallpaperPath
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        cache: false
    }

    ShaderEffectSource {
        id: wallpaperStrip
        width: scrim.width
        height: scrim.height
        sourceItem: wallpaper
        sourceRect: Qt.rect(0, 0, scrim.width, scrim.height)
        textureSize: Qt.size(scrim.width, scrim.height)
        hideSource: true
    }

    ShaderEffect {
        anchors.fill: parent
        visible: wallpaper.status === Image.Ready
        property var source: wallpaperStrip
        property real darkContent: Theme.barContentIsDark ? 1 : 0
        property real stripHeight: height
        fragmentShader: scrim.fragment
    }
}
