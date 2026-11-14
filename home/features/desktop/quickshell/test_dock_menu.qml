import QtQuick
import Quickshell
import "config" as Desktop
import "config/menus"

// Dock menus: macOS 27 contents, callout placement and held-icon state.
ShellRoot {
    QtObject { id: icon }
    Desktop.DockMenu { id: dockMenu; screen: Quickshell.screens[0] }

    function check(value, message) {
        if (!value) throw new Error(message);
    }
    property int step: 0
    Timer {
        interval: 300; running: true; repeat: true
        onTriggered: {
            try {
                const screen = Quickshell.screens[0];
                if (step === 0) {
                    const app = {name: "Editor", entryId: "", running: true, windows: ["0x1", "0x2"]};
                    const entries = dockMenu.appEntries(app);
                    check(entries.map(e => e.isSeparator ? "-" : e.text).join("|") === "Editor|Editor|-|Quit",
                        "Windows, then Quit; untitled windows use the app name");
                    check(entries[0].checkState === Qt.Checked && entries[1].checkState === Qt.Unchecked, "Main window checked");
                    dockMenu.openTrash(icon, false, 600, screen.height - 107);
                } else if (step === 1) {
                    const menu = ContextMenus.node;
                    check(menu && menu.visible && dockMenu.open && dockMenu.heldItem === icon, "Menu opens and holds icon");
                    check(menu.glassNamespace === "quickshell-dock-menu" && menu.calloutHeight === 10, "Pointer namespace and allowance");
                    check(menu._origin.x === 600 - 27 && menu._origin.y + menu.popupHeight === screen.height - 107,
                        "Tip 27 pt from body edge; body ends 13 pt above Dock");
                    // macOS 27 Trash menu body is 108 pt wide.
                    check(Math.abs(menu.popupWidth - 108) <= 1, "Trash menu width " + menu.popupWidth);
                    check(!menu.values[2].enabled, "Empty Trash disabled when empty");
                    dockMenu.close();
                } else if (step === 2) {
                    check(!dockMenu.open && dockMenu.heldItem === null, "Close releases icon");
                    dockMenu.openTrash(icon, true, screen.width - 40, screen.height - 107);
                } else if (step === 3) {
                    const menu = ContextMenus.node;
                    check(menu.glassNamespace === "quickshell-dock-menu-end"
                        && menu._origin.x + menu.popupWidth === screen.width - 40 + 27, "Edge flips pointer to right end");
                    dockMenu.close();
                    console.log("PASS: dock menu contents, callout placement, width, edge flip, held icon");
                    Qt.quit();
                }
                step++;
            } catch (error) {
                console.error("FAIL:", error.message);
                ContextMenus.close();
                Qt.quit();
            }
        }
    }
}
