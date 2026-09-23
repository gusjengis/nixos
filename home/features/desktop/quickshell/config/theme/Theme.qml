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

    // Mac notch mode adds 74 physical rows at 2x scale.
    readonly property int barHeight: 37
    // The bar's tint does not stop at its exclusive zone: BarScrim.qml continues
    // the same ramp below it on the bottom layer, where windows paint over it, so
    // the long fade is only ever visible against the wallpaper. Both surfaces
    // read these, so the seam between them stays invisible.
    // Distance the bar's tint keeps fading past its content. Drawn on the bar's
    // own surface, unreserved and click-through, so it costs no space.
    readonly property int barScrimFade: 56
    readonly property real barScrimPeak: 1.3
    // Where the content ends as a fraction of the whole gradient, so the stops
    // stay put if either height changes.
    readonly property real barScrimContentStop: barHeight / (barHeight + barScrimFade)

    // --- Bar content contrast, reacting to the wallpaper behind it ---
    //
    // The bar's own row of icons and text (Workspaces, Wifi, Clock, ...) has
    // no backing of its own - only the scrim gradient above - so unlike
    // popups (which sit on the always-dark Theme.surface/background below)
    // it needs to react to whatever the wallpaper actually looks like, the
    // way macOS's menu bar switches between light and dark content depending
    // on what's behind it. wallpaperctl samples the strip of the wallpaper
    // that sits behind the bar and writes its WCAG relative luminance (0
    // black, 1 white) into colors.json as barLuminance; everything else here
    // is derived from that one number.
    //
    // Three zones fall out of the same formula:
    //  - Below barTargetLuminance, white content already clears WCAG AA
    //    (4.5:1) on its own, so no scrim is needed at all.
    //  - Up to barCrossover, a black scrim (capped at barScrimMax, the same
    //    ceiling the rest of the UI's translucency uses) is strengthened
    //    just enough to keep pulling the strip's *effective* luminance back
    //    down to barTargetLuminance, so white content keeps its contrast as
    //    the wallpaper gets brighter.
    //  - Past barCrossover even a max-strength scrim cannot save white
    //    content, so the bar switches to dark content instead - which, at
    //    that luminance, already clears AA against the bare wallpaper, so no
    //    scrim is drawn there at all.
    readonly property real barLuminance: wallpaperColors.barLuminance !== undefined ? wallpaperColors.barLuminance : 0.08
    // (1.0 + 0.05) / (L + 0.05) >= 4.5  =>  L <= 0.1833.
    readonly property real barTargetLuminance: 0.1833
    readonly property real barScrimMax: backgroundOpacity
    readonly property real barCrossover: barTargetLuminance / (1 - barScrimMax)
    readonly property bool barContentIsDark: barLuminance >= barCrossover
    readonly property real barScrimAlpha: barContentIsDark ? 0 : Math.max(0, Math.min(barScrimMax, 1 - barTargetLuminance / Math.max(barLuminance, 0.0001)))
    readonly property color barText: barContentIsDark ? "#1d1d1f" : "#ffffff"
    readonly property color barMuted: Qt.rgba(barText.r, barText.g, barText.b, 0.62)
    // A faint wash of barText itself, so a hovered pill's highlight always
    // reads correctly against the barText/barMuted drawn on top of it.
    readonly property color barHoverFill: Qt.rgba(barText.r, barText.g, barText.b, 0.14)
    // Accent colors are tuned for the always-dark popup theme, so on bright
    // wallpapers (dark content) they're pulled toward black to stay legible;
    // on dark wallpapers they're used as matugen generated them.
    readonly property color barAccent: barContentIsDark ? mix(accent, "#000000", 0.4) : accent
    // The color for content drawn on top of a barAccent-filled shape (e.g. the
    // battery's charging bolt), which needs the opposite of barText: barAccent
    // stays light on dark wallpapers and gets pulled dark on bright ones.
    readonly property color barAccentContrast: barContentIsDark ? "#ffffff" : backgroundBase

    function mix(from, to, amount) {
        return Qt.rgba(from.r + (to.r - from.r) * amount, from.g + (to.g - from.g) * amount, from.b + (to.b - from.b) * amount, from.a + (to.a - from.a) * amount);
    }

    readonly property int popupGap: 4
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

    // Black source-over compositing only scales destination RGB, preserving hue.
    // Strength is tied to barScrimAlpha, so this goes to zero outside the
    // zone where white bar content actually needs the help (see above).
    function scrimColor(factor) {
        return Qt.rgba(0, 0, 0, Math.min(1, barScrimAlpha * factor));
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
