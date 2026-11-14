import QtQuick
import Quickshell
import Quickshell.Io
import "config" as Desktop

ShellRoot {
    id: root
    readonly property string folder: Quickshell.env("DOCK_INHERITANCE_TEST_DIR")
    property int stage: 0
    property var nodes: [
        {id: "a", parent_id: null, path: folder + "/a"},
        {id: "b", parent_id: null, path: folder + "/b"},
        {id: "child", parent_id: "a", path: folder + "/child"},
        {id: "leaf", parent_id: "child", path: folder + "/leaf"}
    ]
    Desktop.DockModel {
        id: dock
        contextPath: root.folder + "/child"
        contextNodes: root.nodes
        toplevels: []
        sessionWindows: []
    }
    Desktop.DockModel {
        id: leaf
        contextPath: root.folder + "/leaf"
        contextNodes: root.nodes
        toplevels: []
        sessionWindows: []
    }
    Desktop.DockModel {
        id: parent
        contextPath: root.folder + "/a"
        contextNodes: root.nodes
        toplevels: []
        sessionWindows: []
    }
    Process {
        id: saved
        command: ["cat", root.folder + "/child/.context/state/dock.json"]
        stdout: StdioCollector { id: savedText }
    }
    function check(value, message) { if (!value) throw new Error(message); }
    function pin(model, id, keep) { model.setPinned({entryId: id}, keep); }
    Timer {
        interval: 1500; running: true; repeat: true
        onTriggered: {
            try {
                if (stage === 0) {
                    check(folder.startsWith("/tmp/opencode/"), "Isolated fixture directory required");
                    check(dock.pinned.join() === "kitty" && leaf.pinned.join() === "kitty", "Legacy parent pin inherited through missing child files");
                    pin(dock, "kitty", false);
                    check(!dock.pinned.length, "Inherited pin removed immediately");
                } else if (stage === 1) {
                    check(!leaf.pinned.length && parent.pinned.join() === "kitty", "Removal reaches descendants, not parent");
                    pin(dock, "chromium-browser", true);
                } else if (stage === 2) {
                    check(leaf.pinned.join() === "chromium-browser", "Child addition inherited");
                    pin(parent, "vesktop", true);
                } else if (stage === 3) {
                    check(dock.pinned.includes("vesktop") && leaf.pinned.includes("vesktop"), "Live ancestor file changes reach descendants");
                    check(!dock.pinned.includes("kitty"), "Local removal survives parent edits");
                    dock.reorder("entry:chromium-browser", 1);
                    root.nodes = root.nodes.map(node => node.id === "child" ? Object.assign({}, node, {parent_id: "b"}) : node);
                } else if (stage === 4) {
                    check(dock.pinned.includes("steam") && !dock.pinned.includes("vesktop"), "Reparent replaces inherited pins");
                    check(leaf.pinned.includes("steam") && leaf.pinned.includes("chromium-browser"), "Reparent updates whole subtree, preserving local additions");
                    check(!leaf.pinned.includes("kitty"), "Removal masks new parent's same pin");
                    pin(leaf, "kitty", true);
                } else if (stage === 5) {
                    check(leaf.pinned.includes("kitty") && !dock.pinned.includes("kitty"), "Descendant can override inherited removal");
                    saved.running = true;
                    dock.contextPath = "";
                    check(!dock.pinned.length, "Unsaved context inherits nothing");
                } else if (stage === 6) {
                    const state = JSON.parse(savedText.text);
                    check(state.version === 2 && state.pinned.join() === "chromium-browser" && state.removed.join() === "kitty", "Only local overrides persisted, never inherited pins");
                    dock.contextPath = folder + "/child";
                } else if (stage === 7) {
                    check(dock.pinned.includes("steam") && !dock.pinned.includes("kitty"), "Returning restores current ancestry and overrides");
                    root.nodes = root.nodes.map(node => node.id === "child" ? Object.assign({}, node, {parent_id: null}) : node);
                } else if (stage === 8) {
                    check(dock.pinned.join() === "chromium-browser" && !leaf.pinned.includes("steam"), "Detach removes inherited pins throughout subtree");
                    console.log("PASS: live inheritance, legacy pins, missing files, local overrides, reparent, detach, descendants, persistence");
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
