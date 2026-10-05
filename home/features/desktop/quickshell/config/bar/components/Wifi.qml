import QtQuick
import Quickshell
import "../../theme"
import "../../widgets"

// Wi-Fi menu extra: status glyph in the bar, network list on click.
Rectangle {
    id: root

    required property var controls
    readonly property var state: controls.wifi
    readonly property int signal: state.connected ? state.connected.signal : 0
    readonly property bool popupVisible: popup.visible

    implicitWidth: 30
    implicitHeight: Theme.barItemHeight
    radius: height / 2
    color: popup.visible ? Theme.barHoverFill : "transparent"

    WifiGlyph {
        anchors.centerIn: parent
        powered: root.state.enabled
        level: !root.state.connected ? 0 : root.signal >= 60 ? 3 : root.signal >= 30 ? 2 : 1
        color: Theme.barText
        size: 16
    }

    MouseArea {
        anchors.fill: parent
        onClicked: popup.toggle(root)
    }

    GuardedPopupWindow {
        id: popup

        function toggle(anchorItem) {
            if (visible) {
                visible = false;
                return;
            }
            popup.anchorItem = anchorItem;
            content.reset();
            visible = true;
            root.controls.refreshWifi();
        }

        popupX: root.width - popupWidth
        popupWidth: 310
        popupHeight: content.implicitHeight + 2 * Theme.menuPadding

        WifiPanel {
            id: content
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: Theme.menuPadding }
            controls: root.controls
        }

        Shortcut {
            sequence: "Escape"
            enabled: popup.visible
            onActivated: popup.visible = false
        }
    }
}
