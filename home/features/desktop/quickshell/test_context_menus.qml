//@ pragma UseQApplication
import QtQuick
import Quickshell
import Quickshell.Services.SystemTray
import "config/menus"
import "config/theme"
import "config/bar/components"
import "config/state"

ShellRoot {
    id: test
    // Deterministic lifecycle tests drive focus separately from pointer/grab smoke tests.
    Component.onCompleted: {
        FocusGuard.suspended = true;
        console.log("Loading D-Bus tray providers:", SystemTray.items.values.length);
    }
    property int stage: 0
    property int cancelled: 0
    property int activated: 0
    property var first: null
    property var child: null
    property var trayItem: null
    readonly property bool dbusFixture: Quickshell.env("CONTEXT_MENU_TRAY_FIXTURE") === "1"
    property var fixture: [
        {text: "New Finder Window", enabled: true, icon: "", buttonType: QsMenuButtonType.None},
        {text: "Checked & literal", enabled: true, icon: "", buttonType: QsMenuButtonType.CheckBox, checkState: Qt.Checked},
        {text: "Disabled", enabled: false, icon: ""},
        {text: "", isSeparator: true, enabled: false, icon: ""},
        {text: "First submenu", enabled: true, hasChildren: true, icon: "", children: [
            {text: "Nested submenu", enabled: true, hasChildren: true, icon: "", children: [
                {text: "Grandchild", enabled: true, icon: ""}
            ]}, {text: "Child action", enabled: true, icon: ""}
        ]},
        {text: "Other submenu", enabled: true, hasChildren: true, icon: "", children: [
            {text: "Other child", enabled: true, icon: ""}
        ]},
        {text: "Icon and check", enabled: true, icon: Quickshell.iconPath("folder"),
            buttonType: QsMenuButtonType.CheckBox, checkState: Qt.Checked, shortcut: "⌘O"}
    ]
    function check(value, message) { if (!value) throw new Error(message); }
    function open(position) {
        return ContextMenus.open({owner: test, screen: Quickshell.screens[0], position: position,
            entries: fixture, activate: function() { ++test.activated; }, cancel: function() { ++test.cancelled; }});
    }
    TrayMenu { id: tray }
    FontMetrics { id: fontMetrics; font: Theme.menuFont }
    Timer {
        interval: 300
        running: true
        repeat: true
        onTriggered: {
            try {
                switch (test.stage++) {
                case 0:
                    test.first = test.open(Qt.point(400, 300));
                    test.check(!first.visible && !first.prepared, "New surface remains hidden until layout ready");
                    break;
                case 1:
                    // CoreText menuFontOfSize:0 measurements from reference Mac.
                    const widths = [["New Finder Window",120.6182], ["Show View Options",116.8794],
                        ["Move to Trash",85.5029], ["Child command",94.4277]];
                    test.check(widths.every(sample => Math.abs(fontMetrics.advanceWidth(sample[0]) - sample[1]) < 0.9), "Menu text advances match CoreText reference");
                    test.check(first.visible && first.prepared && first.popupHeight > 100, "First visible surface has complete dimensions");
                    test.check(first.textFont.pixelSize === 13 && first.textFont.weight === Font.Normal, "Shared measured font");
                    first.currentIndex = -1;
                    first.moveHighlight(-1);
                    test.check(first.currentIndex === 6, "Up from no selection starts at last enabled row");
                    first.currentIndex = -1;
                    first.moveHighlight(1);
                    test.check(first.currentIndex === 0, "Down from no selection starts at first row");
                    test.check(first.rowAt(4) !== null, "Real delegates created");
                    first.rowAt(4).hovered();
                    break;
                case 2:
                    test.child = first.tipNode();
                    test.check(child !== first && first.liveNodes.length === 1, "Hover opens child without click");
                    test.check(Math.abs(child._origin.y + child.rowOffset(0) - first._origin.y - first.rowOffset(4)) < 1, "Child first row aligns with parent row");
                    test.check(Math.abs(child._origin.x - first._origin.x - first.popupWidth + Theme.menuPadding) < 1, "Child opens beside parent with native overlap");
                    test.check(child.screen === first.screen && child.textFont === first.textFont, "Child inherits screen and typography");
                    child.rowAt(0).hovered();
                    break;
                case 3:
                    test.check(first.liveNodes.length === 2, "Nested hover opens grandchild");
                    first.rowAt(5).hovered();
                    break;
                case 4:
                    test.check(first.liveNodes.length === 1 && first.tipNode().entryAt(0).text === "Other child", "Sibling replaces entire old branch");
                    first.rowAt(5).hovered();
                    break;
                case 5:
                    test.check(first.liveNodes.length === 1, "Repeated hover does not duplicate child");
                    first.rowAt(0).hovered();
                    break;
                case 6:
                    test.check(first.liveNodes.length === 0, "Hovering leaf closes stale branch");
                    first.currentIndex = 0;
                    first._key({key: Qt.Key_Right, text: "", modifiers: 0});
                    test.check(activated === 0 && ContextMenus.node === first, "Right arrow never activates leaf");
                    first.rowAt(4).hovered();
                    first.rowAt(4).hoverEnded();
                    break;
                case 7:
                    test.check(first.liveNodes.length === 0, "Leaving parent cancels pending submenu");
                    first.currentIndex = 4;
                    first.activateHighlighted();
                    test.check(first.liveNodes.length === 1, "Keyboard opens submenu");
                    first._key({key: Qt.Key_Left, text: "", modifiers: 0});
                    test.check(first.liveNodes.length === 0 && ContextMenus.node === first, "Left closes only child");
                    first.currentIndex = 4;
                    first.activateHighlighted();
                    first._key({key: Qt.Key_Escape, text: "", modifiers: 0});
                    test.check(ContextMenus.node === null && cancelled === 1, "Escape dismisses whole chain once");
                    first = test.open(Qt.point(Quickshell.screens[0].width - 12, 500));
                    break;
                case 8:
                    first.rowAt(4).hovered();
                    break;
                case 9:
                    test.check(first.tipNode()._origin.x < first._origin.x, "Screen edge flips child left");
                    test.check(first.tipNode()._origin.x >= Theme.popupScreenMargin, "Flipped child stays on screen");
                    first = test.open(Qt.point(400, 300));
                    test.check(cancelled === 2, "Opening another menu cancels previous owner");
                    first.currentIndex = 0;
                    first.activateHighlighted();
                    test.check(activated === 1 && cancelled === 2 && ContextMenus.node === null, "Leaf dispatches once without cancel");
                    test.trayItem = SystemTray.items.values.find(item => item.hasMenu && (dbusFixture
                        ? item.title === "QuickShell menu test" : item.title.toLowerCase().includes("steam")))
                        || SystemTray.items.values.find(item => item.hasMenu);
                    test.check(trayItem !== undefined, "Live D-Bus tray provider available");
                    test.check(!dbusFixture || trayItem.title === "QuickShell menu test", "Delayed D-Bus fixture selected");
                    tray.show(trayItem, null);
                    test.check(!tray.node.visible, "D-Bus surface stays hidden before async entries/layout");
                    break;
                case 10:
                    test.check(tray.node !== null && tray.node.source === trayItem.menu, "Tray uses shared factory with real D-Bus handle");
                    test.check(tray.node.values.length > 0, "Real D-Bus entries loaded through QsMenuOpener");
                    console.log("TRAY:", trayItem.title, JSON.stringify(tray.node.values.map(e => ({text:e.text, submenu:e.hasChildren}))));
                    const index = tray.node.values.findIndex(e => e.enabled && e.hasChildren);
                    if (index >= 0) { tray.node.hoverRow(index); }
                    break;
                case 11:
                    if (tray.node.liveNodes.length)
                        test.check(tray.node.tipNode().values.length > 0, "D-Bus submenu children load through opener");
                    if (dbusFixture) {
                        test.check(tray.node.liveNodes.length === 1 && tray.node.tipNode().entryAt(0).text === "Deep submenu", "First real D-Bus submenu opened");
                        tray.node.tipNode().hoverRow(0);
                        break;
                    }
                    tray.close();
                    test.check(ContextMenus.node === null, "Tray dismissal clears shared owner");
                    console.log("PASS: shared factory, hover cascades, nested/sibling teardown, alignment, edge flip, keyboard, cancellation, icons and live D-Bus tray loading");
                    Qt.quit();
                    break;
                case 12:
                    test.check(tray.node.liveNodes.length === 2 && tray.node.tipNode().entryAt(0).text === "Fixture command", "Nested real D-Bus submenu opened");
                    tray.node.tipNode().activateIndex(0);
                    test.check(ContextMenus.node === null, "D-Bus leaf closes whole chain");
                    console.log("PASS: delayed D-Bus nested hover cascade and leaf dispatch");
                    Qt.quit();
                }
            } catch (error) { console.error("FAIL:", error, error.stack); ContextMenus.close(); Qt.quit(); }
        }
    }
}
