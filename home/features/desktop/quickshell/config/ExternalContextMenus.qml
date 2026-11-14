import QtQuick
import Quickshell
import Quickshell.Io
import "menus"

// Chromium exports a menu snapshot over a per-invocation Unix connection.
// Drawing uses the same cascade of row windows, layer surface, and compositor
// glass as tray menus. This service owns the socket, the token handshake, and
// request; ContextMenus owns every window and its lifetime.
Scope {
    id: service

    property var peer: null
    property var menuScreen: null
    readonly property var node: ContextMenus.owner === service ? ContextMenus.node : null
    property string socketPath: Quickshell.env("XDG_RUNTIME_DIR") + "/chromium-quickshell-menu.sock"

    // Writes exactly one token to the peer, then drops it; safe to call again.
    function write(token) {
        const connection = peer
        peer = null
        if (connection && connection.connected) {
            connection.write(String(token) + "\n")
            connection.flush()
            connection.connected = false
        }
    }
    // Leaf activated: deliver the entry token, then the cascade tears itself down.
    function leafHandler(entry) {
        write(entry ? entry.token : 0)
    }
    // Dismissal (Escape, pointer-outside, or connection drop): report -1.
    function cancelHandler() {
        write(-1)
    }

    // Full teardown, used for error/disconnect paths where no cascade is running
    // but a token must still be reported.
    function finish(token) {
        write(token)
        ContextMenus.close(service)
    }

    function normalize(items) {
        return items.map(item => ({
            text: item.mnemonic ? item.text.replace(/&&/g, "\u0000").replace(/&/g, "").replace(/\u0000/g, "&") : item.text,
            enabled: item.enabled === true,
            isSeparator: item.isSeparator === true,
            buttonType: item.checkable ? QsMenuButtonType.CheckBox : QsMenuButtonType.None,
            checkState: item.checked ? Qt.Checked : Qt.Unchecked,
            icon: item.icon || "",
            shortcut: item.shortcut || "",
            token: item.token,
            hasChildren: item.children && item.children.length > 0,
            children: item.children && item.children.length ? normalize(item.children) : []
        }))
    }

    function show(connection, point) {
        if (peer !== connection || !connection.connected)
            return
        const screens = Quickshell.screens
        menuScreen = screens.find(screen => point.x >= screen.x && point.y >= screen.y
            && point.x < screen.x + screen.width && point.y < screen.y + screen.height) || screens[0]
        if (!menuScreen) {
            finish(-1)
            return
        }
        let items
        try {
            items = normalize(connection.request.items)
        } catch (error) {
            finish(-1)
            return
        }
        if (!items.length) {
            finish(-1)
            return
        }
        ContextMenus.open({
            owner: service,
            keyboard: connection.request.keyboard === true,
            screen: menuScreen,
            position: Qt.point(point.x - menuScreen.x, point.y - menuScreen.y),
            entries: items,
            activate: function(entry) { service.leafHandler(entry) },
            cancel: function() { service.cancelHandler() }
        })
    }

    SocketServer {
        active: true
        path: service.socketPath
        handler: Socket {
            id: connection
            property var request: null
            onConnectedChanged: {
                if (!connected && service.peer === connection)
                    service.finish(-1)
            }
            parser: SplitParser {
                onRead: message => {
                    if (connection.request !== null)
                        return
                    try {
                        const data = JSON.parse(message)
                        if (!Array.isArray(data.items) || !data.items.length)
                            throw new Error("Empty menu")
                        service.finish(-1)
                        connection.request = data
                        service.peer = connection
                        position.running = true
                    } catch (error) {
                        connection.write("-1\n")
                        connection.flush()
                        connection.connected = false
                    }
                }
            }
            property Process positionProbe: Process {
                id: position
                command: ["hyprctl", "-j", connection.request && connection.request.keyboard ? "activewindow" : "cursorpos"]
                stdout: StdioCollector {
                    onStreamFinished: {
                        try {
                            const location = JSON.parse(text)
                            const point = connection.request.keyboard
                                ? {x: location.at[0] + (connection.request.x || 0), y: location.at[1] + (connection.request.y || 0)}
                                : location
                            service.show(connection, point)
                        } catch (error) {
                            if (service.peer === connection)
                                service.finish(-1)
                        }
                    }
                }
            }
        }
    }

}
