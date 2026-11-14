import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland

// Send geometry only. Wallpaper sampling and color changes happen in the same
// compositor frame as the wallpaper, not in a second Qt color animation.
QtObject {
    id: root
    required property string namespace
    property bool enabled: false
    property var rectangles: []
    property var clip: null
    property real radius: 13
    readonly property bool active: enabled && Theme.desktopTintComposited && registered
    property bool registered: false
    property string previous: ""

    function refresh() {
        if (enabled && Theme.desktopTintComposited)
            update.restart();
        else
            registered = false;
    }
    function rect(value) {
        return "{x=" + Number(value.x) + ",y=" + Number(value.y)
            + ",width=" + Number(value.width) + ",height=" + Number(value.height)
            + ",radius=" + Number(value.radius || 0) + ",hovered=" + (value.hovered ? "true" : "false") + "}";
    }
    onEnabledChanged: refresh()
    onRectanglesChanged: refresh()
    onClipChanged: refresh()
    onRadiusChanged: refresh()
    property var capability: Connections {
        target: Theme
        function onDesktopTintCompositedChanged() { root.refresh(); }
    }
    property var reload: Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (event.name === "configreloaded") {
                root.previous = "";
                root.refresh();
            }
        }
    }
    property var update: Timer {
        interval: 0
        onTriggered: {
            if (!root.enabled || !Theme.desktopTintComposited) return;
            if (request.running) { restart(); return; }
            const cards = root.rectangles.filter(r => r.width > 0 && r.height > 0).slice(0, 32);
            const code = "hl.plugin.hyprglass.layer(" + JSON.stringify(root.namespace)
                + ",{mac_inset=80,mac_radius=" + root.radius
                + ",mac_shadow=0.2,mac_outline=0.2,mac_apple=\"apple-menu\",mac_neutral_rects={"
                + cards.map(r => root.rect(r)).join(",") + "}"
                + (root.clip ? ",mac_neutral_clip=" + root.rect(root.clip) : "") + "})";
            if (code === root.previous) { root.registered = true; return; }
            request.command = ["hyprctl", "eval", code];
            request.running = true;
            root.previous = code;
        }
    }
    property var request: Process {
        id: request
        onExited: (code, status) => {
            root.registered = code === 0 && status === 0;
            if (!root.registered) root.previous = "";
        }
    }
}
