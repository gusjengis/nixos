import QtQuick
import Quickshell
import "config" as Desktop
import "config/state" as State

// Use an isolated runtime/signature and PATH fixture: contextctl close must wait
// for several seconds, while contextctl open must immediately print "ok".
ShellRoot {
    Desktop.SessionPicker { id: picker }
    property int phase: 0
    property bool switched: false
    property bool passed: false

    function check(condition, message) {
        if (!condition) throw new Error(message);
    }

    Connections {
        target: State.DesktopSessions
        function onCompleted(action) {
            if (action === "open") switched = true;
        }
    }

    Timer {
        running: true
        repeat: true
        interval: 300
        onTriggered: {
            try {
                const state = State.DesktopSessions;
                check(Quickshell.env("CONTEXT_CLOSE_TEST") === "1", "Requires isolated command fixtures");
                check(!state.error, "Unexpected command failure: " + state.error);
                if (phase === 0) {
                    state.snapshot = { active: "s1", sessions: [
                        { id: "s1", name: "Closing", window_count: 1 },
                        { id: "s2", name: "Other", window_count: 0 }
                    ] };
                    state.contextCatalog = { contexts: [{ id: "other", name: "Other", runtime_id: "s2" }] };
                    picker.beginClose();
                    check(picker.closeTarget !== null, "Close confirmation must select runtime");
                    picker.confirmClose();
                    check(state.closeRequest.running, "Close checkpoint must run in background");
                    check(!picker.awaiting && !state.busy, "Background close must not occupy foreground action slot");
                    check(!picker.closeTarget && !picker.visible, "Accepted close must dismiss confirmation");
                    phase = 1;
                } else if (phase === 1) {
                    check(state.closeRequest.running, "Fixture must keep checkpoint pending");
                    check(state.openSessions.find(item => item.id === "s1").closing, "Pending close must remain visible");
                    picker.toggle(false);
                    check(picker.visible, "Picker must reopen during checkpoint");
                    check(state.switchSession("other"), "Other context must remain switchable");
                    phase = 2;
                } else if (phase === 2) {
                    check(state.closeRequest.running, "Switch must finish before checkpoint");
                    check(switched && !state.busy, "Foreground switch must finish independently");
                    picker.visible = false;
                    phase = 3;
                } else if (!state.closeRequest.running) {
                    check(!state.openSessions.find(item => item.id === "s1").closing, "Finished request must clear pending status");
                    passed = true;
                    console.log("Session close: picker reopening and switching remain responsive during checkpoint");
                    Qt.quit();
                }
            } catch (error) {
                console.error("FAILED:", error);
                Qt.quit();
            }
        }
    }
}
