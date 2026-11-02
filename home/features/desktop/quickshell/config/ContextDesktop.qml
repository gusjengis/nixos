import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "state"

Scope {
    id: root
    readonly property string contextId: DesktopSessions.contextCatalog.active_context || ""
    readonly property var contextNode: (DesktopSessions.contextCatalog.nodes || []).find(node => node.id === contextId && !node.is_group) || ({})
    readonly property string directory: contextNode.path || ""

    DesktopFilesModel { id: files; directory: root.directory }
    PersistentProperties {
        id: preferences
        reloadableId: "context-desktop-preferences"
        property int iconSize: 48
        property string sortBy: "name"
    }
    Variants {
        model: Quickshell.screens
        delegate: PanelWindow {
            id: window
            required property var modelData
            screen: modelData
            visible: root.directory !== ""
            anchors { top: true; bottom: true; left: true; right: true }
            exclusionMode: ExclusionMode.Ignore
            color: "transparent"
            WlrLayershell.layer: WlrLayer.Bottom
            WlrLayershell.namespace: "quickshell-context-desktop"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

            DesktopSurface {
                id: surface
                anchors.fill: parent
                directory: root.directory
                entries: files.entries
                error: files.error
                iconSize: preferences.iconSize
                sortBy: preferences.sortBy
                onAction: (operation, names) => files.run(operation, names)
                onIconSizeRequested: size => preferences.iconSize = size
                onSortRequested: order => preferences.sortBy = order
                onWallpaperRequested: Quickshell.execDetached(["quickshell", "ipc", "call", "wallpaper", "open"])
            }
            Connections {
                target: files
                function onCreated(name) { surface.selected = [name]; }
            }
        }
    }
}
