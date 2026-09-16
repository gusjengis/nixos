import QtQuick
import Quickshell.Io
import Quickshell.Widgets

// Launches an application on a remote host in the background.
// Reports failures back to the launcher that owns it.
Process {
    id: root
    required property var launcher
    property bool didStart: false
    property string appName
    property string hostName

    onStarted: didStart = true
    onRunningChanged: {
        if (!running && !didStart) {
            launcher.error = "Cannot start remote helper. Run rehome on this machine.";
            launcher.visible = true;
            root.destroy();
        }
    }

    stderr: StdioCollector { id: launchErrors }

    onExited: (code, status) => {
        if (code !== 0 || status !== 0) {
            launcher.error = appName + " on " + hostName + ": " + (launchErrors.text.trim() || "Remote launch failed");
            launcher.visible = true;
        }
        root.destroy();
    }
}