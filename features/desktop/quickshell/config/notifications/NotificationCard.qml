import QtQuick
import Quickshell
import Quickshell.Services.Notifications
import "../theme"

Rectangle {
    id: root

    required property var entry
    property bool showTime: false
    signal dismissRequested()

    readonly property var current: entry.notification
    readonly property color urgencyColor: current.urgency === NotificationUrgency.Critical
        ? Theme.danger
        : current.urgency === NotificationUrgency.Low ? Theme.muted : Theme.accentStrong
    readonly property string iconSource: current.image || (current.appIcon
        ? Quickshell.iconPath(current.appIcon, true) : "")

    implicitHeight: content.implicitHeight + 24
    radius: Theme.windowRadius
    color: Theme.background
    border { width: Theme.windowBorderWidth; color: root.urgencyColor }

    Row {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
        spacing: 10

        Item {
            width: 38
            height: 38

            Rectangle {
                anchors.fill: parent
                radius: Theme.radius
                color: Theme.surface

                Text {
                    anchors.centerIn: parent
                    text: root.current.appName.slice(0, 1).toUpperCase()
                    color: Theme.accent
                    font { family: Theme.fontFamily; pixelSize: 16; bold: true }
                }
            }

            Image {
                anchors.fill: parent
                source: root.iconSource
                fillMode: Image.PreserveAspectFit
                visible: status === Image.Ready
                sourceSize { width: 38; height: 38 }
            }
        }

        Column {
            width: content.width - 38 - 28 - content.spacing * 2
            spacing: 4

            Row {
                width: parent.width

                Text {
                    width: parent.width - (timeLabel.visible ? timeLabel.width + 8 : 0)
                    text: root.current.appName || "Notification"
                    color: Theme.muted
                    elide: Text.ElideRight
                    font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2; bold: true }
                }

                Text {
                    id: timeLabel
                    visible: root.showTime
                    text: Qt.formatTime(new Date(root.entry.receivedAt), "HH:mm")
                    color: Theme.muted
                    font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2 }
                }
            }

            Text {
                width: parent.width
                text: root.current.summary || root.current.appName || "Notification"
                color: Theme.text
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: Theme.fontSize; bold: true }
            }

            Text {
                width: parent.width
                visible: text.length > 0
                text: root.current.body
                textFormat: Text.PlainText
                color: Theme.text
                wrapMode: Text.Wrap
                maximumLineCount: 4
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 1 }
            }
        }

        Rectangle {
            width: 28
            height: 28
            radius: Theme.radius
            color: closeMouse.containsMouse ? Theme.surfaceHover : "transparent"

            Text {
                anchors.centerIn: parent
                text: "x"
                color: Theme.muted
                font { family: Theme.fontFamily; pixelSize: Theme.fontSize; bold: true }
            }

            MouseArea {
                id: closeMouse
                anchors.fill: parent
                hoverEnabled: true
                onClicked: root.dismissRequested()
            }
        }
    }
}
