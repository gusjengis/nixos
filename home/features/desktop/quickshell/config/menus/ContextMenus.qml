pragma Singleton
import QtQuick
import Quickshell
import Quickshell.Io
import "../theme"

// The only context-menu factory. Callers adapt their data/actions; presentation,
// focus, cascading, typography and lifetime are owned here.
Scope {
    id: service
    property var node: null
    property var owner: null
    readonly property bool visible: node !== null && node.visible
    Component.onDestruction: close()

    function open(request) {
        close();
        owner = request.owner || null;
        const properties = {
            nodeFactory: factory,
            entries: request.entries || [],
            source: request.source || null,
            anchorItem: request.anchorItem || null,
            screen: request.screen || (request.anchorItem && request.anchorItem.QsWindow.window
                ? request.anchorItem.QsWindow.window.screen : Quickshell.screens[0]),
            keyboardDriven: request.keyboard === true,
            leafHandler: request.activate || null,
            cancelHandler: request.cancel || null
        };
        // A callout keeps the window's own placement binding, which follows its size.
        if (request.callout) properties.callout = request.callout;
        else properties.absolutePosition = request.position || null;
        const root = factory.createObject(null, properties);
        if (!root) { owner = null; return null; }
        node = root;
        root.present();
        return root;
    }
    function close(requestOwner) {
        if (requestOwner && owner !== requestOwner) return;
        if (node) node.closeCascade(true);
    }
    function released(root) {
        if (node === root) { node = null; owner = null; }
        root.destroy();
    }
    Component {
        id: factory
        ContextMenuWindow {
            id: popup
            onFinished: service.released(popup)
        }
    }
    IpcHandler {
        target: "contextMenus"
        function dismiss(): void { service.close(); }
        function snapshot(): string {
            const root = service.node;
            return JSON.stringify(root ? [root].concat(root.liveNodes).map(menu => ({
                visible: menu.visible, prepared: menu.prepared, dbus: menu.source !== null,
                namespace: menu.glassNamespace,
                x: menu._origin.x, y: menu._origin.y, width: menu.popupWidth, height: menu.popupHeight,
                currentIndex: menu.currentIndex, fontSize: menu.textFont.pixelSize,
                rows: menu.values.map(entry => ({text: menu.label(entry), enabled: entry.enabled,
                    separator: entry.isSeparator, submenu: entry.hasChildren}))
            })) : []);
        }
    }
}
