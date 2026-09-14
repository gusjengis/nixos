pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    property var wallpaperColors: ({})
    // 0 is fully transparent; 1 is fully opaque.
    readonly property real backgroundOpacity: 0.6
    readonly property color backgroundBase: wallpaperColors.background || "#151922"
    readonly property color surfaceBase: wallpaperColors.surface || "#202633"
    readonly property color surfaceHoverBase: wallpaperColors.surfaceHover || "#2a3242"
    readonly property color background: withBackgroundOpacity(backgroundBase)
    readonly property color surface: withBackgroundOpacity(surfaceBase)
    readonly property color surfaceHover: withBackgroundOpacity(surfaceHoverBase)
    readonly property color text: wallpaperColors.text || "#e8edf5"
    readonly property color muted: wallpaperColors.muted || "#8d99aa"
    readonly property color accent: wallpaperColors.accent || "#8ec5ff"
    readonly property color accentStrong: wallpaperColors.accentStrong || "#5aa7f7"
    readonly property color warning: wallpaperColors.warning || "#f2c879"
    readonly property color danger: wallpaperColors.danger || "#ef8d8d"
    readonly property color border: wallpaperColors.border || "#344052"

    readonly property int barHeight: 40
    readonly property int radius: 8
    readonly property int spacing: 8
    readonly property int fontSize: 13
    readonly property string fontFamily: "sans-serif"

    property int windowBorderWidth: 2
    property int windowRadius: 16
    property color windowBorder: "#aa595959"

    function withBackgroundOpacity(color) {
        return Qt.rgba(color.r, color.g, color.b, backgroundOpacity);
    }

    function loadWallpaperColors() {
        try {
            wallpaperColors = JSON.parse(colorsFile.text());
        } catch (error) {
            console.warn("Cannot load wallpaper colors:", error);
        }
    }

    property var colorsFile: FileView {
        id: colorsFile
        path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state")
            + "/wallpaper/colors.json"
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: loadWallpaperColors()
    }

    function refreshHyprland() {
        if (!borderWidthRequest.running)
            borderWidthRequest.running = true;
        if (!radiusRequest.running)
            radiusRequest.running = true;
        if (!borderColorRequest.running)
            borderColorRequest.running = true;
    }

    property var borderWidthRequest: Process {
        id: borderWidthRequest
        command: ["hyprctl", "-j", "getoption", "general:border_size"]
        stdout: StdioCollector { id: borderWidthOutput }
        onExited: (code, status) => {
            if (code === 0 && status === 0)
                windowBorderWidth = JSON.parse(borderWidthOutput.text).int;
        }
    }

    property var radiusRequest: Process {
        id: radiusRequest
        command: ["hyprctl", "-j", "getoption", "decoration:rounding"]
        stdout: StdioCollector { id: radiusOutput }
        onExited: (code, status) => {
            if (code === 0 && status === 0)
                windowRadius = JSON.parse(radiusOutput.text).int;
        }
    }

    property var borderColorRequest: Process {
        id: borderColorRequest
        command: ["hyprctl", "-j", "getoption", "general:col.inactive_border"]
        stdout: StdioCollector { id: borderColorOutput }
        onExited: (code, status) => {
            if (code !== 0 || status !== 0)
                return;
            const gradient = JSON.parse(borderColorOutput.text).gradient.split(" ")[0];
            windowBorder = "#" + gradient;
        }
    }

    property var hyprlandRefresh: Timer {
        interval: 10000
        repeat: true
        running: true
        triggeredOnStart: true
        onTriggered: refreshHyprland()
    }
}
