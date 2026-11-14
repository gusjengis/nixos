import QtQuick
import Quickshell
import Quickshell.Io

// One uniform wallpaper-affinity color per window, matching AppKit. The region
// is screen-local and excludes compositor shadow padding. No screenshot or
// underlying application content is sampled.
QtObject {
    id: root
    property var screen: null
    property rect region: Qt.rect(0, 0, 0, 0)
    property bool enabled: false
    property bool composited: false
    property var palette: null
    readonly property color surface: Theme.neutralColor(palette && palette.surface, Theme.windowSurface)
    readonly property color card: Theme.neutralColor(palette && palette.card, Theme.cardSurface)
    readonly property color hover: Theme.neutralColor(palette && palette.hover, Theme.cardSurfaceHover)
    readonly property color border: Theme.neutralColor(palette && palette.border, Theme.neutralBorder)

    function refresh() {
        if (enabled && screen && region.width > 0 && region.height > 0)
            requestTimer.restart();
    }
    onScreenChanged: refresh()
    onRegionChanged: refresh()
    onEnabledChanged: refresh()

    property var changes: Connections {
        target: Theme
        function onDesktopTintGenerationChanged() { root.refresh(); }
    }
    property var requestTimer: Timer {
        interval: 25
        onTriggered: {
            if (!root.enabled || !root.screen)
                return;
            if (request.running) {
                restart();
                return;
            }
            // The shell can outlive a profile switch; its inherited PATH can
            // still point at the previous Home Manager generation.
            request.command = [Quickshell.env("HOME") + "/.nix-profile/bin/desktop-tint", "sample",
                String(root.screen.x + root.region.x), String(root.screen.y + root.region.y),
                String(root.region.width), String(root.region.height)];
            request.running = true;
        }
    }
    property var request: Process {
        id: request
        stdout: StdioCollector {
            onStreamFinished: {
                try { root.palette = JSON.parse(text); }
                catch (error) { /* Keep the last complete material while reconnecting. */ }
            }
        }
    }
}
