pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    property var wallpaperColors: ({})
    // Liquid Glass tint changes popup density, not menu-bar contrast.
    property real glassTint: 1
    readonly property real backgroundOpacity: 0.56 + 0.24 * glassTint
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

    // Mac notch mode adds 74 physical rows at 2x scale.
    readonly property int barHeight: 30
    readonly property int barScrimHeight: 183
    // Historical JSON key now stores mean per-pixel CIE L* of the top 30 rows.
    readonly property real barLightness: wallpaperColors.barLuminance !== undefined ? wallpaperColors.barLuminance : 0.08
    readonly property bool barContentIsDark: barLightness >= 0.786
    readonly property color barText: barContentIsDark ? "#000000" : "#ffffff"
    // For content drawn on a barText-filled shape (e.g. the active workspace).
    readonly property color barTextInverse: barContentIsDark ? "#ffffff" : "#000000"
    readonly property color barMuted: Qt.rgba(barText.r, barText.g, barText.b, 0.62)
    // A faint wash of barText itself, so a hovered pill's highlight always
    // reads correctly against the barText/barMuted drawn on top of it.
    readonly property color barHoverFill: Qt.rgba(barText.r, barText.g, barText.b, 0.09)
    // Open menu-extra highlight: a capsule, 22px tall on the 30px bar.
    readonly property int barItemHeight: 22

    // Menus hang 1px below the bar; the glass outline occupies that row.
    readonly property int popupGap: 1
    readonly property int popupScreenMargin: 6

    // Liquid Glass dropdowns. Radii and padding must match the hyprglass
    // layers configured in hyprland/config/glass.lua.
    property bool glassActive: false
    property bool groupedGlassActive: false
    readonly property int glassShadowPadding: 80
    readonly property int menuRadius: 13
    readonly property int panelRadius: 22
    // macOS 27 menu metrics at 1x, measured from reference captures.
    readonly property int menuRowHeight: 24
    readonly property int menuPadding: 5
    readonly property int menuSeparatorHeight: 11
    readonly property int menuTextInset: 12
    readonly property int menuFontSize: 14
    readonly property color menuText: Qt.rgba(1, 1, 1, 0.9)
    readonly property color menuSecondaryText: Qt.rgba(1, 1, 1, 0.42)
    readonly property color menuSeparator: Qt.rgba(1, 1, 1, 0.12)
    readonly property color menuHighlight: "#007aff"
    readonly property int menuHighlightRadius: 8

    property var glassProbe: Process {
        command: ["hyprctl", "-j", "hyprglass", "status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const status = JSON.parse(text);
                    glassActive = status.features && status.features.layers && status.features.layers.active === true;
                    groupedGlassActive = glassActive && status.macRects === true;
                } catch (error) {
                    glassActive = false;
                    groupedGlassActive = false;
                }
            }
        }
    }
    // The plugin is loaded by the launcher's startup helper, possibly after
    // QuickShell starts; keep probing until it is present.
    property var glassProbeTimer: Timer {
        interval: 3000
        repeat: true
        running: !glassActive || !groupedGlassActive
        triggeredOnStart: true
        onTriggered: {
            if (!glassProbe.running)
                glassProbe.running = true;
        }
    }
    readonly property int radius: 8
    readonly property int spacing: 8
    readonly property int fontSize: 15
    readonly property string fontFamily: "SF Pro"
    readonly property string iconFontFamily: "Symbols Nerd Font Mono"

    property int windowBorderWidth: 2
    property int windowRadius: 16
    property color windowBorder: "#aa595959"

    function withBackgroundOpacity(color) {
        return Qt.rgba(color.r, color.g, color.b, backgroundOpacity);
    }

    function setGlassTint(value) {
        if (!Number.isFinite(value))
            return;
        glassTint = Math.max(0, Math.min(1, value));
        glassTintFile.setText(glassTint.toFixed(3) + "\n");
    }

    onGlassTintChanged: {
        if (glassTintSyncTimer)
            glassTintSyncTimer.restart();
    }

    property var glassTintSync: Process {}
    property var glassTintSyncTimer: Timer {
        interval: 25
        onTriggered: {
            if (glassTintSync.running) {
                restart();
                return;
            }
            glassTintSync.command = ["hyprctl", "eval", "if hl.plugin.hyprglass then hl.plugin.hyprglass.config({mac={tint=" + glassTint.toString() + "}}) end"];
            glassTintSync.running = true;
        }
    }

    function barPopupY(anchorItem) {
        if (!anchorItem)
            return barHeight + popupGap;
        return barHeight + popupGap - anchorItem.mapToItem(null, 0, 0).y;
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
        path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/wallpaper/colors.json"
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: loadWallpaperColors()
    }

    property string wallpaperPath: displayedPath || currentPath
    property string displayedPath: ""
    property string currentPath: ""

    property var displayedFile: FileView {
        path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/wallpaper/displayed"
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: displayedPath = text().trim()
    }

    property var currentFile: FileView {
        path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/wallpaper/current"
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: currentPath = text().trim()
    }

    property var glassTintFile: FileView {
        path: (Quickshell.env("XDG_CONFIG_HOME") || Quickshell.env("HOME") + "/.config") + "/quickshell/theme/glass-tint"
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            const value = Number(text().trim());
            if (Number.isFinite(value)) {
                glassTint = Math.max(0, Math.min(1, value));
                glassTintSyncTimer.restart();
            }
        }
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
        stdout: StdioCollector {
            id: borderWidthOutput
        }
        onExited: (code, status) => {
            if (code === 0 && status === 0)
                windowBorderWidth = JSON.parse(borderWidthOutput.text).int;
        }
    }

    property var radiusRequest: Process {
        id: radiusRequest
        command: ["hyprctl", "-j", "getoption", "decoration:rounding"]
        stdout: StdioCollector {
            id: radiusOutput
        }
        onExited: (code, status) => {
            if (code === 0 && status === 0)
                windowRadius = JSON.parse(radiusOutput.text).int;
        }
    }

    property var borderColorRequest: Process {
        id: borderColorRequest
        command: ["hyprctl", "-j", "getoption", "general:col.inactive_border"]
        stdout: StdioCollector {
            id: borderColorOutput
        }
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
