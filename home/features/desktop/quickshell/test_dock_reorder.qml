import QtQuick
import Quickshell
import Quickshell.Io
import "config" as Desktop

ShellRoot {
    id: root
    property int stage: 0
    readonly property string folder: Quickshell.env("DOCK_REORDER_TEST_DIR")
    QtObject { id: kittyWindow; property var lastIpcObject: ({address: "kitty", class: "kitty"}) }
    QtObject { id: chromiumWindow; property var lastIpcObject: ({address: "chromium", class: "chromium-browser"}) }
    QtObject { id: unknownWindow; property var lastIpcObject: ({address: "unknown", class: "unknown-app"}) }
    Desktop.DockModel {
        id: dock
        toplevels: [kittyWindow, chromiumWindow, unknownWindow]
        sessionWindows: ["kitty", "chromium", "unknown"]
        contextPath: root.folder
    }
    Desktop.DockModel {
        id: restored
        toplevels: []
        sessionWindows: []
        contextPath: ""
    }
    Process {
        id: saved
        command: ["cat", root.folder + "/.context/state/dock.json"]
        stdout: StdioCollector { id: savedText }
    }
    Process {
        id: savedOther
        command: ["cat", root.folder + "-other/.context/state/dock.json"]
        stdout: StdioCollector { id: savedOtherText }
    }
    function check(value, message) { if (!value) throw new Error(message); }
    function keys() { return dock.items.map(app => dock.orderKey(app)).join("|"); }
    function fixture(id) { return {key: id, entryId: id === "unknown-app" ? "" : id, windows: [id], cycle: [id], name: id, icon: ""}; }
    Timer {
        interval: 300; running: true; repeat: true
        onTriggered: {
            try {
                if (stage === 0) {
                    check(!!folder && folder.startsWith("/tmp/opencode/"), "Provide isolated test directory");
                    dock.apps = [fixture("kitty"), fixture("chromium-browser"), fixture("unknown-app")];
                    dock.setPinned(dock.apps[0], true);
                    dock.reorder("entry:chromium-browser", 1);
                    check(keys().endsWith("entry:chromium-browser|entry:kitty|unknown-app"), "Running tile crosses pinned tile");
                    check(dock.pinned.join() === "kitty", "Drag does not pin running app");
                    dock.reorder("unknown-app", 0);
                    check(dock.items[0].permanent && dock.items[1].key === "unknown-app", "Clamp before Finder");
                    const before = keys();
                    dock.reorder("entry:" + dock.finderId, 3);
                    check(keys() === before, "Finder cannot move");
                    dock.reorder("entry:missing", 1);
                    check(keys() === before, "Disappeared app ignored");
                    dock.rebuildItems();
                    check(keys() === before, "Metadata rebuild preserves order");
                } else if (stage === 1) {
                    saved.running = true;
                } else if (stage === 2) {
                    const state = JSON.parse(savedText.text);
                    check(state.version === 2 && state.pinned.join() === "kitty", "Local pins persisted");
                    check(state.order.join() === "unknown-app,entry:chromium-browser,entry:kitty", "Full order persisted");
                    restored.apps = dock.apps;
                    restored.contextPath = folder;
                } else if (stage === 3) {
                    check(restored.items.map(app => restored.orderKey(app)).join("|") === keys(), "Restart restores order");
                    dock.setPinned(dock.apps.find(app => app.entryId === "chromium-browser"), true);
                    dock.reorder("entry:chromium-browser", 1);
                    check(dock.pinned.join() === "chromium-browser,kitty", "Pinned tiles reorder too");
                    dock.apps = [];
                    check(dock.items.slice(1).map(app => app.entryId).join() === "chromium-browser,kitty", "Idle pins retain reordered positions");
                    dock.apps = [fixture("kitty"), fixture("chromium-browser"), fixture("unknown-app")];
                    // Switch immediately, while the preceding write is pending.
                    dock.contextPath = folder + "-other";
                } else if (stage === 4) {
                    check(dock.order.length === 0 && dock.pinned.length === 0, "Context switch clears foreign order and pins");
                    dock.reorder("entry:chromium-browser", 1);
                    dock.contextPath = "";
                    dock.reorder("unknown-app", 1);
                    check(dock.items[1].key === "unknown-app", "Unsaved context supports runtime reordering");
                    const runtime = dock.runtimeSession;
                    dock.runtimeSession = "other-runtime";
                    check(dock.order.length === 0, "Unsaved sessions do not inherit order");
                    dock.runtimeSession = runtime;
                    check(dock.items[1].key === "unknown-app", "Returning to unsaved session restores runtime order");
                } else if (stage === 5) {
                    saved.running = true;
                    savedOther.running = true;
                } else if (stage === 6) {
                    check(JSON.parse(savedText.text).pinned.join() === "chromium-browser,kitty", "Switch during write preserves original context's pins");
                    const other = JSON.parse(savedOtherText.text);
                    check(other.pinned.length === 0 && other.order[0] === "entry:chromium-browser", "New context writes its own state");
                    console.log("PASS: dock reordering, Finder fixed, pin preservation, rebuild, persistence, restore, context isolation");
                    Qt.quit();
                }
                stage++;
            } catch (error) {
                console.error("FAIL stage", stage, error.message, error.stack);
                Qt.exit(1);
            }
        }
    }
}
