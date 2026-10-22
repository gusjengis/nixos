import QtQuick
import Quickshell
import Quickshell.Io
import "config/state" as State

// Headless test. PATH fixture must require --background and return "ok" while
// a detached worker keeps the file in CONTEXT_RESTORE_MARKER at "running".
ShellRoot {
    property int phase: 0
    property int completions: 0
    property bool passed: false
    FileView {
        id: marker
        path: Quickshell.env("CONTEXT_RESTORE_MARKER")
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
    }
    Connections {
        target: State.DesktopSessions
        function onCompleted(action) { completions++; }
    }
    function check(condition, message) {
        if (!condition) throw new Error(message);
    }
    Timer {
        interval: 400
        running: true
        repeat: true
        onTriggered: {
            try {
                const state = State.DesktopSessions;
                check(Quickshell.env("CONTEXT_RESTORE_TEST") === "1", "Requires isolated command fixture");
                check(!state.error, "Unexpected launch failure: " + state.error);
                if (phase === 0) {
                    state.contextCatalog = { contexts: [{id: "first"}, {id: "other"}] };
                    check(state.switchSession("first"), "First restore must be accepted");
                } else {
                    check(!state.busy && completions === phase, "Picker action slot remained blocked by restoration");
                    check(marker.text().trim() === "running", "Detached worker must still be restoring");
                    if (phase === 1)
                        check(state.switchSession("other"), "Another context must remain available");
                    else if (phase === 2)
                        check(state.create("New"), "Create-and-open must use background restoration");
                    else {
                        passed = true;
                        console.log("Session restore: detached startup releases foreground slot for other opens and creation");
                        Qt.quit();
                    }
                }
                phase++;
            } catch (error) {
                console.error("FAILED:", error);
                Qt.quit();
            }
        }
    }
}
