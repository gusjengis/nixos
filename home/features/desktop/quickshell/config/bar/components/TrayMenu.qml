import QtQuick
import "../../menus"

// D-Bus adapter only. All presentation belongs to ContextMenus.
Item {
    id: owner
    readonly property var node: ContextMenus.owner === owner ? ContextMenus.node : null
    readonly property bool menuVisible: node !== null && node.visible
    readonly property Item anchorItem: node ? node.anchorItem : null
    function show(trayItem, anchor) {
        if (!trayItem || !trayItem.hasMenu) return;
        ContextMenus.open({owner: owner, source: trayItem.menu, anchorItem: anchor,
            activate: function(entry) { entry.triggered(); }});
    }
    function close() { ContextMenus.close(owner); }
    Component.onDestruction: close()
}
