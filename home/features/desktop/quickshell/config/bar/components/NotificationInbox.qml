import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import Quickshell
import "../../notifications"
import "../../theme"
import "../../widgets"

// macOS Notification Center: no panel of its own, just a floating title,
// a clear-all button and the notification cards over the desktop. The popup
// surface is transparent; only the cards carry glass (blurred through the
// bar layer's blur_popups rule, which skips fully transparent pixels).
Item {
    id: root

    required property var notificationService
    required property Item popupAnchor
    readonly property var history: notificationService ? notificationService.history : []
    readonly property bool popupVisible: popup.visible
    // Room left of and above each card for its hover close button.
    readonly property int overhang: 8

    function toggle(anchorItem) {
        if (popup.visible) {
            popup.visible = false;
            return;
        }
        popup.anchor.item = anchorItem;
        popup.visible = true;
    }


    GuardedPopupWindow {
        id: popup

        readonly property real maxListHeight: (screen ? screen.height : 1000) - Theme.barHeight - header.height - 60

        anchor.rect.x: root.popupAnchor.width
            - (anchor.item ? anchor.item.mapToItem(root.popupAnchor, 0, 0).x : 0)
            - width - 10
        anchor.rect.y: Theme.barPopupY(anchor.item)
        implicitWidth: 380
        implicitHeight: header.height + 10 + (root.history.length > 0 ? list.height : empty.implicitHeight + 8)
        color: "transparent"
        onVisibleChanged: root.notificationService.centerOpen = visible

        RowLayout {
            id: header
            anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: root.overhang + 6 }
            height: 40

            Text {
                Layout.fillWidth: true
                text: "Notification Center"
                color: Theme.barText
                font { family: Theme.fontFamily; pixelSize: 22; weight: Font.DemiBold }
                layer.enabled: !Theme.barContentIsDark
                layer.effect: MultiEffect {
                    shadowEnabled: true
                    shadowColor: "#000000"
                    shadowOpacity: 0.35
                    shadowBlur: 0.4
                    shadowVerticalOffset: 1
                }
            }

            Rectangle {
                visible: root.history.length > 0
                implicitWidth: 28
                implicitHeight: 28
                radius: 14
                color: clearMouse.containsMouse ? Theme.surfaceHover : Theme.background
                border { width: 1; color: Qt.rgba(1, 1, 1, 0.12) }

                SFSymbol {
                    anchors.centerIn: parent
                    symbol: "xmark"
                    size: 11
                    color: Theme.text
                }

                MouseArea {
                    id: clearMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: root.notificationService.clear()
                }
            }
        }

        Text {
            id: empty
            anchors { left: header.left; top: header.bottom; topMargin: 4 }
            visible: root.history.length === 0
            text: "No Notifications"
            color: Theme.barMuted
            font { family: Theme.fontFamily; pixelSize: 14 }
        }

        ListView {
            id: list
            anchors { left: parent.left; right: parent.right; top: header.bottom; topMargin: 10 - root.overhang }
            height: Math.min(contentHeight + topMargin + bottomMargin, popup.maxListHeight)
            visible: root.history.length > 0
            topMargin: root.overhang
            leftMargin: root.overhang
            spacing: 10
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.history

            delegate: NotificationCard {
                required property var modelData
                width: list.width - root.overhang
                entry: modelData
                onDismissRequested: root.notificationService.dismiss(entry.key)
            }
        }

        Shortcut {
            sequence: "Escape"
            enabled: popup.visible
            onActivated: popup.visible = false
        }
    }
}
