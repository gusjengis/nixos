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
    implicitHeight: 24
    radius: 6
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
            anchor.item = anchorItem;
            content.reset();
            visible = true;
            root.controls.refreshWifi();
        }

        anchor.rect.x: root.width - width
        anchor.rect.y: Theme.barPopupY(anchor.item)
        implicitWidth: 380
        implicitHeight: Math.min(480, content.implicitHeight + 32)
        color: "transparent"

        Rectangle {
            anchors.fill: parent
            radius: Theme.windowRadius
            color: Theme.background
            border { width: Theme.windowBorderWidth; color: Theme.windowBorder }
        }

        WifiPanel {
            id: content
            anchors { fill: parent; margins: 16 }
            controls: root.controls
        }

        Shortcut {
            sequence: "Escape"
            enabled: popup.visible
            onActivated: popup.visible = false
        }
    }
}
