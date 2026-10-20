import QtQuick
import Quickshell
import "config" as Desktop
import "config/state" as State

// Run with qs -p this-file using an unused HYPRLAND_INSTANCE_SIGNATURE so the
// singleton cannot read or act on real desktop state. No windows are shown.
ShellRoot {
    Desktop.SessionPicker { id: picker }

    function check(condition, message) {
        if (!condition)
            throw new Error(message);
    }

    Timer {
        running: true
        interval: 300
        onTriggered: {
            const state = State.DesktopSessions;
            state.snapshot = {
                active: "s1", previous: "s2",
                sessions: [
                    { id: "s1", name: "Working", window_count: 2 },
                    { id: "s2", name: "Runtime only", window_count: 0 }
                ]
            };
            state.contextCatalog = { contexts: [
                { id: "context-one", name: "Working", runtime_id: "s1" },
                { id: "context-two", name: "Saved only", runtime_id: null }
            ] };

            check(!picker.dispensary, "Default menu must be runtime switcher");
            check(picker.results.length === 2, "Switcher must show both live sessions");
            check(picker.results.every(item => item.runtime_id === item.id), "Switcher must use runtime IDs");
            check(!picker.results.some(item => item.name === "Saved only"), "Saved-only context leaked into switcher");
            picker.submit(true);
            check(state.pendingAction === "", "Switcher must not create contexts");

            picker.dispensary = true;
            check(picker.results.length === 2, "Dispensary must list saved contexts");
            check(picker.results.every(item => item.persistent), "Runtime-only session leaked into dispensary");
            check(picker.results.some(item => item.runtime_id === "s1"), "Running saved context must remain in dispensary");
            picker.beginClose();
            check(picker.closeTarget === null, "Dispensary must not close live sessions");

            picker.dispensary = false;
            state.snapshot = { active: "", sessions: [] };
            check(picker.results.length === 0, "Switcher must update when sessions close");
            picker.submit(false);
            check(state.pendingAction === "", "Empty switcher must not create contexts");

            console.log("Session picker: runtime/dispensary filtering and action guards passed");
            Qt.quit();
        }
    }
}
