import QtQuick
import QtQuick.Layouts
import "../../theme"

Rectangle {
    id: root

    property var batteryService: null
    readonly property bool popupVisible: popup.visible

    visible: !!batteryService && batteryService.available
    implicitWidth: 34
    implicitHeight: 28
    radius: Theme.radius
    color: hover.hovered ? Theme.barHoverFill : "transparent"

    Item {
        anchors.centerIn: parent
        implicitWidth: 22
        implicitHeight: 14

        Rectangle {
            x: 1
            y: 2
            width: 18
            height: 11
            radius: 2
            color: "transparent"
            border { width: 1; color: Theme.barText }

            Rectangle {
                anchors { left: parent.left; top: parent.top; bottom: parent.bottom; margins: 2 }
                width: Math.max(1, (parent.width - 4)
                    * (root.batteryService ? root.batteryService.percentage : 0) / 100)
                radius: 1
                color: root.batteryService && root.batteryService.percentage <= 15
                    ? Theme.danger
                    : root.batteryService && root.batteryService.charging ? Theme.barAccent : Theme.barText
            }

            Text {
                anchors.centerIn: parent
                visible: !!root.batteryService && root.batteryService.charging
                text: ""
                color: Theme.barAccentContrast
                font { family: Theme.iconFontFamily; pixelSize: 9 }
            }
        }

        Rectangle {
            x: 19
            y: 5
            width: 2
            height: 5
            radius: 1
            color: Theme.barText
        }
    }

    HoverHandler {
        id: hover
        blocking: false
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: popup.toggle(root)
    }

    BatteryPopup {
        id: popup
        batteryService: root.batteryService
    }

}
