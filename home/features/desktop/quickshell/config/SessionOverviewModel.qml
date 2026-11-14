import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import "SessionOverview.js" as Overview

Scope {
    id: root
    readonly property var windows: Hyprland.toplevels.values.map(toplevel =>
        Object.assign({}, toplevel.lastIpcObject, { captureSource: toplevel.wayland }))
    readonly property var monitors: Hyprland.monitors.values.map(monitor => monitor.lastIpcObject)
    property real specialBlurRadius: 12
    property real specialDim: 0

    Process {
        id: effects
        command: ["hyprctl", "-j", "--batch", "getoption decoration:blur:enabled; getoption decoration:blur:special; getoption decoration:blur:size; getoption decoration:blur:passes; getoption decoration:dim_special"]
        running: !!Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE")
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const options = (text.match(/\{[^{}]*\}/g) || []).map(value => JSON.parse(value));
                    if (options.length !== 5) return;
                    // Dual-Kawase footprint, reduced with the monitor thumbnail.
                    root.specialBlurRadius = options[0].bool && options[1].bool
                        ? options[2].int * Math.pow(2, options[3].int) : 0;
                    root.specialDim = options[4].float;
                } catch (_) {}
            }
        }
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (event.name === "configreloaded") effects.running = true;
        }
    }

    // Reuse the Dock's desktop-entry matching and generated macOS icon cache.
    DockModel { id: appCatalog }

    function overview(session) {
        return Overview.overview(session, windows, monitors.filter(monitor => !!monitor));
    }

    function apps(windows) {
        const apps = [];
        for (const window of windows) {
            const key = appCatalog.appKey(window.initialClass || window.class || "", window.title);
            if (key && !apps.some(app => app.key === key))
                apps.push(Object.assign({ key: key }, appCatalog.describe(key)));
        }
        return apps;
    }
}
