import QtQuick
import Quickshell.Io
import Quickshell.Widgets

// Fetches an application list (local export, hosts, or remote listing).
// Reports results back to the launcher that owns it.
Process {
    id: root
    required property var launcher
    property bool didStart: false

    onStarted: didStart = true
    onRunningChanged: {
        if (!running && !didStart && launcher.request === root) {
            launcher.request = null;
            launcher.error = "Cannot start remote helper. Run rehome on this machine.";
            root.destroy();
        }
    }

    stdout: StdioCollector { id: output }
    stderr: StdioCollector { id: errors }

    onExited: (code, status) => {
        if (launcher.request === root) {
            launcher.request = null;
            if (code !== 0 || status !== 0) {
                launcher.error = errors.text.trim() || "Request failed. Check SSH access and rebuild both machines.";
            } else {
                try {
                    const entries = JSON.parse(output.text);
                    if (!Array.isArray(entries))
                        throw new Error("Expected an application list");
                    launcher.entries = entries;
                } catch (e) {
                    launcher.error = "Invalid remote response: " + e.message;
                }
            }
        }
        root.destroy();
    }
}