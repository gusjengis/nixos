import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    id: root
    property string directory: ""
    property var entries: []
    property string error: ""
    property bool loaded: false
    readonly property bool busy: listing.running || action.running
    // A long-lived shell can retain a PATH pointing at the previous generation.
    readonly property string helper: Quickshell.env("HOME") + "/.nix-profile/bin/context-desktop-files"
    signal created(string name)

    onDirectoryChanged: {
        entries = [];
        error = "";
        loaded = false;
        refresh();
    }

    function refresh() {
        if (!directory || listing.running) return;
        listing.owner = directory;
        listing.running = true;
    }

    function run(operation, names) {
        if (!directory || action.running) return;
        action.owner = directory;
        action.operation = operation;
        action.names = names || [];
        error = "";
        action.running = true;
    }

    property var poll: Timer {
        interval: 2500
        repeat: true
        running: root.directory !== ""
        onTriggered: root.refresh()
    }
    property var listing: Process {
        id: listing
        property string owner: ""
        command: [root.helper, "list", owner]
        stdout: StdioCollector { id: output }
        stderr: StdioCollector { id: errors }
        onExited: (code, status) => {
            if (owner !== root.directory) { Qt.callLater(root.refresh); return; }
            try {
                if (code || status) throw new Error(errors.text.trim() || "Context folder unavailable");
                const value = JSON.parse(output.text);
                if (!Array.isArray(value)) throw new Error("Invalid desktop response");
                if (JSON.stringify(value) !== JSON.stringify(root.entries)) root.entries = value;
                root.error = "";
            } catch (error) {
                root.entries = [];
                root.error = error.message;
            }
            root.loaded = true;
        }
    }
    property var action: Process {
        id: action
        property string owner: ""
        property string operation: ""
        property var names: []
        command: [root.helper, operation, owner, "--"].concat(names)
        stdout: StdioCollector { id: actionOutput }
        stderr: StdioCollector { id: actionErrors }
        onExited: (code, status) => {
            if (owner !== root.directory) return;
            if (code || status) root.error = actionErrors.text.trim() || "Desktop action failed";
            else {
                if (operation === "new-folder") {
                    try { root.created(JSON.parse(actionOutput.text).created); } catch (_) {}
                }
                root.refresh();
            }
        }
    }
}
