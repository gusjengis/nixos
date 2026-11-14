//@ pragma UseQApplication
import QtQuick
import Quickshell
import "config" as Desktop
import "config/state"

ShellRoot {
    id: test
    Component.onCompleted: FocusGuard.suspended = true
    property int stage: 0
    property var actions: []
    function check(value, message) {
        if (!value)
            throw new Error(message);
    }
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
                {
                    name: "Notes & plans.txt",
                    icon: "text-plain",
                    folder: false,
                    modified: 1
                },
                {
                    name: "Documents",
                    icon: "folder",
                    folder: true,
                    modified: 2
                },
                {
                    name: "A rather long desktop document name.pdf",
                    icon: "application-pdf",
                    folder: false,
                    modified: 3
                }
            ]
            onAction: (operation, names) => test.actions.push({
                    operation: operation,
                    names: names
                })
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
                    test.check(menu && menu.node && !menu.node.visible && menu.items.some(item => item.operation === "new-folder"), "Empty-space menu prepares shared controls before mapping");
                    test.check(menu.node._origin.x + menu.node.popupWidth <= window.screen.width, "Menu stays on screen horizontally");
                    test.check(menu.node._origin.y + menu.node.popupHeight <= window.screen.height, "Menu stays on screen vertically");
                    captureMenu.start();
                    surface.grabToImage(result => result.saveToFile("/tmp/opencode/context-desktop-implemented.png"));
                    test.stage = 1;
                } else {
                    surface.showMenu(400, 300, true);
                    const itemMenu = surface.data.find(item => item.objectName === "desktop-context-menu");
                    test.check(itemMenu.node.entryAt(0).text === "Open" && itemMenu.node.entryAt(3).operation === "trash", "Desktop-file menu uses shared entries");
                    itemMenu.node.activateIndex(0);
                    test.check(test.actions[1].operation === "open" && test.actions[1].names[0] === "Documents", "Shared desktop-file action preserves selected names");
                    surface.directory = "/fixture/second";
                    test.check(surface.selected.length === 0, "Switch clears selection");
                    surface.entries = [];
                    test.check(surface.ordered.length === 0, "Empty context clears icons");
                    console.log("PASS: desktop sorting, multiselect, opening, external deletion, menu, context isolation");
                    Qt.quit();
                }
            } catch (error) {
                console.error("FAILED:", error);
                Qt.quit();
            }
        }
    }
    Timer {
        id: captureMenu
        interval: 250
        onTriggered: {
            const menu = surface.data.find(item => item.objectName === "desktop-context-menu");
            test.check(menu.node.prepared && menu.node.visible, "Desktop menu maps only after preparation");
            menu.node.body.grabToImage(result => result.saveToFile("/tmp/opencode/context-desktop-menu-implemented.png"));
        }
    }
}
