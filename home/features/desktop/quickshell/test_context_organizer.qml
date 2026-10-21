import QtQuick
import Quickshell
import "config" as Desktop
import "config/state" as State
import "config/OrganizerModel.js" as Model

// Isolated signature and XDG_CONFIG_HOME; never launches or mutates contexts.
ShellRoot {
    Desktop.ContextOrganizer { id: organizer }
    property bool passed: false

    function check(condition, message) {
        if (!condition) throw new Error(message);
    }
    function row(id, label, parent, ancestors) {
        return { id: id, label: label, parent_id: parent, ancestors: ancestors,
            breadcrumb: ancestors.concat([label]).join(" / "), child_count: 0,
            is_group: false, runtime_id: null };
    }
    Timer {
        running: true
        interval: 300
        onTriggered: {
            try {
                const state = State.DesktopSessions;
                const nodes = [row("computing", "Computing", null, []),
                    row("nixos", "NixOS", "computing", ["computing"]),
                    row("context", "Desktop Contexts", "nixos", ["computing", "nixos"]),
                    row("theme", "macOS Theme", "nixos", ["computing", "nixos"]),
                    row("hardware", "Hardware", null, [])];
                state.contextCatalog = { contexts: [], nodes: nodes };
                organizer.select("computing", 0, 0);
                organizer.enterColumn(1);
                check(organizer.currentNode.id === "nixos", "Right must select child");
                organizer.enterColumn(2);
                check(organizer.currentNode.id === "context", "Nested children must sort by label");
                organizer.select("theme", 2, Qt.ShiftModifier);
                check(organizer.selectedIds.length === 2, "Shift selection must include siblings");
                organizer.cut();
                check(organizer.clipboard.length === 2, "Cut must preserve batch selection");
                organizer.enterColumn(1);
                organizer.enterColumn(2);
                check(organizer.currentNode.id === "theme", "Right must remember child selection");
                organizer.reveal("context");
                check(JSON.stringify(organizer.parents) === JSON.stringify([null, "computing", "nixos", "context"]), "Reveal must reconstruct ancestor columns");
                check(organizer.depth === 2, "Reveal must focus context column");
                organizer.enterColumn(3);
                check(organizer.selectedIds.length === 0 && organizer.currentParent === "context", "Empty child column must permit creation/paste");
                check(Model.search(nodes, "dsk ctx")[0].id === "context", "Fuzzy multiword search must find subsequences");
                check(Model.search(nodes, "NixOS")[0].id === "nixos", "Exact name must rank first");
                check(Model.search(nodes, "nix theme")[0].id === "theme", "Search must match hierarchy and label");
                const destinations = Model.destinations(nodes, ["nixos"], "");
                check(!destinations.some(item => ["nixos", "context", "theme"].includes(item.id)), "Move destinations must exclude subtree");
                check(Model.highlights("<Context>", "ctx").includes("&lt;"), "Highlighted labels must escape markup");
                check(!state.pendingAction, "Navigation must not launch or mutate contexts");
                organizer.reveal("context");
                organizer.handleKey({ key: Qt.Key_D, modifiers: Qt.ControlModifier, isAutoRepeat: false, text: "", accepted: false });
                check(organizer.dialogMode === "delete", "Ctrl+D must open deletion confirmation");
                check(organizer.dialogIds.length === 1 && organizer.dialogIds[0] === "context", "Confirmation must freeze selected IDs");
                check(!state.pendingAction, "Opening confirmation must not delete anything");
                organizer.closeDialog();
                check(!organizer.dialogMode && !state.pendingAction, "Cancel must leave context unchanged");
                nodes[2].working_directory = "/etc/nixos";
                organizer.editWorkingDirectory(nodes[2]);
                check(organizer.dialogMode === "working-directory", "Preview path must open working directory editor");
                check(organizer.dialogIds[0] === "context", "Directory edit must freeze target context ID");
                organizer.closeDialog();
                organizer.editWorkingDirectory({ id: "group", is_group: true });
                check(!organizer.dialogMode && !state.pendingAction, "Groups and cancelling edits must not change configuration");
                passed = true;
                console.log("Context organizer: navigation, selection, memory, fuzzy search and move guards passed");
            } catch (error) { console.error("FAILED:", error); return; }
            Qt.quit();
        }
    }
}
