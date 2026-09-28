import QtQuick
import QtQuick.Controls
import "../theme"

// Control Center slider: a thick capsule track whose fill runs under a
// round knob, with the module's symbol drawn inside the track's left end.
Slider {
    id: control

    property string symbol: ""
    signal symbolClicked()

    implicitWidth: 240
    implicitHeight: 22
    padding: 0
    from: 0
    to: 1
    focusPolicy: Qt.NoFocus
    opacity: enabled ? 1 : 0.45

    background: Rectangle {
        x: control.leftPadding
        y: control.topPadding + control.availableHeight / 2 - height / 2
        width: control.availableWidth
        height: control.height
        radius: height / 2
        color: Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, 0.16)

        Rectangle {
            width: control.height + control.visualPosition * (parent.width - control.height)
            height: parent.height
            radius: parent.radius
            color: Theme.text
        }
    }

    handle: Rectangle {
        x: control.leftPadding + control.visualPosition * (control.availableWidth - width)
        y: control.topPadding + control.availableHeight / 2 - height / 2
        implicitWidth: control.height
        implicitHeight: control.height
        radius: height / 2
        color: "#ffffff"
        border.width: 1
        border.color: Qt.rgba(0, 0, 0, 0.14)
    }

    SFSymbol {
        z: 2
        anchors { left: parent.left; leftMargin: 5; verticalCenter: parent.verticalCenter }
        symbol: control.symbol
        size: 12
        color: Qt.rgba(0, 0, 0, 0.55)

        MouseArea {
            anchors { fill: parent; margins: -4 }
            cursorShape: Qt.PointingHandCursor
            onClicked: control.symbolClicked()
        }
    }
}
