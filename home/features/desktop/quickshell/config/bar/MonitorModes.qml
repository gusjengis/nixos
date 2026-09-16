import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io

Scope {
    id: root

    property var hugeMargins: ({})

    function enabledFor(screen) {
        const monitor = Hyprland.monitorFor(screen);
        return monitor ? root.hugeMargins[monitor.name] === true : false;
    }

    function load() {
        try {
            const data = JSON.parse(stateFile.text());
            root.hugeMargins = data.hugeMargins || {};
        } catch (error) {
            root.hugeMargins = {};
        }
    }

    FileView {
        id: stateFile
        path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/hyprland-monitor-modes.json"
        preload: true
        watchChanges: true
        // Hosts with no configured monitor modes never create this file.
        printErrors: false
        onFileChanged: reload()
        onLoaded: root.load()
    }
}
