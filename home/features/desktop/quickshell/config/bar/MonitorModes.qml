import QtQuick
import Quickshell
import Quickshell.Io

Scope {
    id: root

    property var hugeMargins: ({})
    property bool initialized: false

    function load() {
        try {
            const data = JSON.parse(stateFile.text());
            root.hugeMargins = data.hugeMargins || {};
        } catch (error) {
            root.hugeMargins = {};
        }
        root.initialized = true;
    }

    FileView {
        id: stateFile
        path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/hyprland-monitor-modes.json"
        preload: true
        blockLoading: true
        watchChanges: true
        // Hosts with no configured monitor modes never create this file.
        printErrors: false
        onFileChanged: reload()
        onLoaded: root.load()
    }

    Component.onCompleted: load()
}
