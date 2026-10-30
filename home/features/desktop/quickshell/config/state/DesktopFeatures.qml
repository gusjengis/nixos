pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    id: root
    readonly property var settings: {
        try { return JSON.parse(configuration.text()); }
        catch (_) { return ({}); }
    }
    readonly property bool contexts: settings.contexts !== false
    readonly property bool personal: settings.personal !== false
    readonly property bool development: settings.development !== false

    property var configuration: FileView {
        path: (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share")
            + "/quickshell/features.json"
        preload: true
        blockLoading: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
    }
}
