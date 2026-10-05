import QtQuick
import "../theme"

// macOS 27 switch: blue capsule track with an elongated glass knob.
// Stateless: `checked` stays bound to its source, clicks emit `toggled`.
Rectangle {
    id: root

    property bool checked: false
    signal toggled(bool value)

    implicitWidth: 52
    implicitHeight: 23
    radius: height / 2
    opacity: enabled ? 1 : 0.45
    color: checked ? Theme.menuHighlight : Qt.rgba(1, 1, 1, mouse.containsMouse ? 0.2 : 0.14)

    Behavior on color { ColorAnimation { duration: 140 } }

    Rectangle {
        id: knob
        y: (parent.height - height) / 2
        x: root.checked ? parent.width - width - 2 : 2
        width: 31
        height: parent.height - 4
        radius: height / 2
        color: "#ffffff"

        Behavior on x { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: root.toggled(!root.checked)
    }
}
