import QtQuick
import Quickshell
import "../../notifications"
import "../../theme"

Item {
    id: root

    required property var notificationService
    required property Item popupAnchor
    readonly property var history: notificationService ? notificationService.history : []

    readonly property bool popupVisible: popup.visible

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

        anchor.rect.x: root.popupAnchor.width
            - (anchor.item ? anchor.item.mapToItem(root.popupAnchor, 0, 0).x : 0)
            - width - 10
        anchor.rect.y: Theme.barPopupY(anchor.item)
        implicitWidth: 420
        implicitHeight: 520
        color: "transparent"

        Rectangle {
            anchors.fill: parent
            radius: Theme.windowRadius
            color: Theme.background
            border { width: Theme.windowBorderWidth; color: Theme.windowBorder }
        }

        Item {
            anchors { fill: parent; margins: 14 }

            Text {
                id: title
                anchors { left: parent.left; top: parent.top }
                text: "Notifications"
                color: Theme.text
                font { family: Theme.fontFamily; pixelSize: 16; bold: true }
            }

            Rectangle {
                anchors { right: parent.right; verticalCenter: title.verticalCenter }
                width: clearLabel.implicitWidth + 16
                height: 26
                radius: Theme.radius
                visible: root.history.length > 0
                color: clearMouse.containsMouse ? Theme.surfaceHover : Theme.surface

                Text {
                    id: clearLabel
                    anchors.centerIn: parent
                    text: "Clear all"
                    color: Theme.muted
                    font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 1 }
                }

                MouseArea {
                    id: clearMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: root.notificationService.clear()
                }
            }

            Text {
                anchors.centerIn: parent
                visible: root.history.length === 0
                text: "No recent notifications"
                color: Theme.muted
                font { family: Theme.fontFamily; pixelSize: Theme.fontSize }
            }

            ListView {
                id: list
                anchors { left: parent.left; right: parent.right; top: title.bottom; bottom: parent.bottom; topMargin: 14 }
                visible: root.history.length > 0
                spacing: 8
                clip: true
                model: root.history

                delegate: NotificationCard {
                    required property var modelData
                    width: list.width
                    entry: modelData
                    showTime: true
                    onDismissRequested: root.notificationService.dismiss(entry.key)
                }
            }
        }

        Shortcut {
            sequence: "Escape"
            enabled: popup.visible
            onActivated: popup.visible = false
        }
    }
}
