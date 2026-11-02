//@ pragma UseQApplication
import QtQuick
import Quickshell
import "config" as Desktop

ShellRoot {
    id: test
    property int stage: 0
    property var actions: []
    function check(value, message) { if (!value) throw new Error(message); }
    FloatingWindow {
        id: window
        visible: true
        implicitWidth: 1280
        implicitHeight: 800
        color: "#253e58"
        Desktop.DesktopSurface {
            id: surface
            anchors.fill: parent
            directory: "/fixture/first"
            entries: [
                { name: "Notes & plans.txt", icon: "text-plain", folder: false, modified: 1 },
                { name: "Documents", icon: "folder", folder: true, modified: 2 },
                { name: "A rather long desktop document name.pdf", icon: "application-pdf", folder: false, modified: 3 }
            ]
            onAction: (operation, names) => test.actions.push({operation: operation, names: names})
        }
    }
    Timer {
        interval: 1000
        repeat: true
        running: true
        onTriggered: {
            try {
                if (test.stage === 0) {
                    test.check(surface.ordered[0].name.endsWith(".pdf"), "Name sorting");
                    surface.choose("Documents", 0);
                    surface.choose("Notes & plans.txt", Qt.ControlModifier);
                    test.check(surface.selected.length === 2, "Modifier multiselect");
                    surface.openSelection();
                    test.check(test.actions[0].operation === "open" && test.actions[0].names.length === 2, "Open selected literal filenames");
                    surface.choose("Documents", Qt.ControlModifier);
                    test.check(surface.selected.length === 1, "Modifier deselect");
                    surface.sortBy = "modified";
                    test.check(surface.ordered[0].modified === 3, "Date sorting");
                    surface.entries = surface.entries.filter(entry => entry.name !== "Notes & plans.txt");
                    test.check(surface.selected.length === 0, "External deletion clears selection");
                    surface.selected = ["Documents"];
                    surface.showMenu(1275, 795, false);
                    const menu = surface.data.find(item => item.objectName === "desktop-context-menu");
                    test.check(menu && menu.visible && menu.items.some(item => item.operation === "new-folder"), "Empty-space menu controls");
                    test.check(menu._origin.x + menu.popupWidth <= window.screen.width, "Menu stays on screen horizontally");
                    test.check(menu._origin.y + menu.popupHeight <= surface.height, "Menu stays on screen vertically");
                    menu.body.grabToImage(result => result.saveToFile("/tmp/opencode/context-desktop-menu-implemented.png"));
                    surface.grabToImage(result => result.saveToFile("/tmp/opencode/context-desktop-implemented.png"));
                    test.stage = 1;
                } else {
                    surface.directory = "/fixture/second";
                    test.check(surface.selected.length === 0, "Switch clears selection");
                    surface.entries = [];
                    test.check(surface.ordered.length === 0, "Empty context clears icons");
                    console.log("PASS: desktop sorting, multiselect, opening, external deletion, menu, context isolation");
                    Qt.quit();
                }
            } catch (error) { console.error("FAILED:", error); Qt.quit(); }
        }
    }
}
