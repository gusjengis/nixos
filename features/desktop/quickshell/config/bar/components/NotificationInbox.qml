import QtQuick
import QtQuick.Layouts
import Quickshell
import "../../notifications"
import "../../theme"

Rectangle {
    id: root

    required property var notificationService
    readonly property var history: notificationService ? notificationService.history : []

    implicitWidth: content.implicitWidth + 14
    implicitHeight: 28
    radius: Theme.radius
    color: mouse.containsMouse || popup.visible ? Theme.surfaceHover : "transparent"

    RowLayout {
        id: content
        anchors.centerIn: parent
        spacing: 4

        Text {
            text: ""
            color: root.history.length > 0 ? Theme.accent : Theme.muted
            font { family: Theme.iconFontFamily; pixelSize: 16 }
        }

        Text {
            text: root.history.length.toString()
            color: root.history.length > 0 ? Theme.accent : Theme.muted
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 1; bold: true }
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
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
            visible = true;
        }

        anchor.rect.x: (anchor.item ? anchor.item.width : 0) - width
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
