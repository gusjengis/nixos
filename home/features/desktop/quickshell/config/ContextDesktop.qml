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
            // Hyprland's follow_mouse hands keyboard focus to any hovered
            // OnDemand layer, so stray cursor drift onto the wallpaper would
            // steal focus from windows. Accept keyboard only after a click on
            // the desktop, and give it up once the pointer leaves.
            property bool keyboardWanted: false
            WlrLayershell.keyboardFocus: keyboardWanted ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None

            DesktopSurface {
                id: surface
                anchors.fill: parent
                directory: root.directory
                entries: files.entries
                error: files.error
                iconSize: preferences.iconSize
                sortBy: preferences.sortBy
                onInteracted: window.keyboardWanted = true
                onAction: (operation, names) => files.run(operation, names)
                onIconSizeRequested: size => preferences.iconSize = size
                onSortRequested: order => preferences.sortBy = order
                onWallpaperRequested: Quickshell.execDetached(["quickshell", "ipc", "call", "wallpaper", "open"])

                HoverHandler {
                    onHoveredChanged: if (!hovered) window.keyboardWanted = false
                }
            }
            Connections {
                target: files
                function onCreated(name) { surface.selected = [name]; }
            }
        }
    }
}
