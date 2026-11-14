import QtQuick
import Quickshell
import Quickshell.Io
import "config" as Desktop

// Per-context Dock pins: Finder permanent, Keep in Dock / Remove from Dock,
// persistence in <context>/.context/state/dock.json, and window focus action.
ShellRoot {
    id: root
    property int stage: 0
    readonly property string folder: Quickshell.env("DOCK_PINS_TEST_DIR") || "/tmp/opencode/dock-pins-test"
    QtObject { id: kittyWindow; property var lastIpcObject: ({ address: "0xk", class: "kitty", focusHistoryID: 0 }) }
    Desktop.DockModel {
        id: dock
        toplevels: [kittyWindow]
        sessionWindows: ["0xk"]
        contextPath: root.folder
    }
    Desktop.DockMenu { id: menu; dockModel: dock }
    Process {
        id: saved
        command: ["cat", root.folder + "/.context/state/dock.json"]
        stdout: StdioCollector { id: savedText }
        function reload() { running = true; }
        function text() { return savedText.text; }
    }

    function check(value, message) { if (!value) throw new Error(message); }
    function labels(entries) { return entries.map(e => e.isSeparator ? "-" : e.text).join("|"); }
    function item(id) { return dock.items.find(app => app.entryId === id); }

    
    Timer {
        interval: 400; running: true; repeat: true
        onTriggered: {
            try {
                if (stage === 0) {
                    check(dock.items[0].entryId === dock.finderId && dock.items[0].permanent, "Finder always first");
                    check(labels(menu.options(dock.items[0])) === "", "Finder has no Options");
                    const kitty = item("kitty");
                    check(kitty && kitty.running && !kitty.pinned, "Running app unpinned by default");
                    const opts = menu.options(kitty);
                    check(opts[0].text === "Options" && opts[0].children[0].text === "Keep in Dock"
                        && opts[0].children[0].checkState === Qt.Unchecked, "Keep in Dock unchecked");
                    check(labels(menu.appEntries(kitty)).endsWith("|-|Options|-|Quit"), "Options precedes Quit: " + labels(menu.appEntries(kitty)));
                    dock.setPinned(kitty, true);
                    check(item("kitty").pinned && dock.items[1].entryId === "kitty", "Pinned in place after Finder");
                } else if (stage === 1) {
                    saved.reload();
                } else if (stage === 2) {
                    check(JSON.parse(saved.text()).pinned.join() === "kitty", "Saved in context folder (created): " + saved.text());
                    check(menu.options(item("kitty"))[0].children[0].checkState === Qt.Checked, "Keep in Dock checked when pinned");
                    kittyWindow.lastIpcObject = {};
                    const idle = item("kitty");
                    check(idle && !idle.running && idle.windows.length === 0, "Pinned app stays after quitting");
                    check(labels(menu.appEntries(idle)) === "Options|-|Open"
                        && menu.appEntries(idle)[0].children[0].text === "Remove from Dock", "Not-running menu matches macOS");
                    dock.setPinned(idle, false);
                    check(!item("kitty"), "Remove from Dock drops idle app");
                } else if (stage === 3) {
                    saved.reload();
                } else if (stage === 4) {
                    check(JSON.parse(saved.text()).pinned.length === 0, "Unpin persisted");
                    // Another context's file is independent.
                    dock.contextPath = "";
                    check(dock.pinned.length === 0 && !dock.canPin({entryId: "kitty"}), "No folder: no pins");
                    check(typeof menu.focusWindow === "function", "Window rows dispatch focus");
                    console.log("PASS: dock pins per context, Finder permanent, Keep/Remove from Dock, persistence, focus action");
                    Qt.quit();
                }
                stage++;
            } catch (error) {
                console.error("FAIL:", error.message);
                Qt.exit(1);
            }
        }
    }
}
