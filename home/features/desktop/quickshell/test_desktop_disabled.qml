import QtQuick
import Quickshell
import "config" as Desktop
import "config/state" as State
import "config/bar" as Bar

// Use isolated XDG_DATA_HOME with all features false and an unused compositor signature.
ShellRoot {
    LazyLoader {
        id: contexts
        active: State.DesktopFeatures.contexts
        source: "config/DesktopContexts.qml"
    }
    Bar.UsageService { id: usage }
    Desktop.Launcher { id: launcher }

    Timer {
        running: true
        interval: 300
        onTriggered: {
            if (State.DesktopFeatures.contexts || State.DesktopFeatures.personal || State.DesktopFeatures.development)
                throw new Error("Disabled module choices were not loaded");
            if (contexts.item || State.DesktopSessions.available)
                throw new Error("Desktop contexts instantiated while disabled");
            if (State.DesktopSessions.contextFile.path !== "" || State.DesktopSessions.stateFile.path !== "")
                throw new Error("Disabled contexts still watch runtime state");
            if (State.DesktopSessions.workspaceName(3, "HDMI-A-1") !== "3")
                throw new Error("Plain workspace numbering unavailable");
            launcher.startProjectSearch();
            if (launcher.projectSearch !== null || State.DesktopSessions.request.running)
                throw new Error("Disabled desktop launched context/development work");
            console.log("PASS: module-controlled contexts unloaded, watchers inactive, plain workspaces available");
            Qt.quit();
        }
    }
}
