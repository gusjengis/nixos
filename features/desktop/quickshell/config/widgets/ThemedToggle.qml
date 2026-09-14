import QtQuick
import "../theme"

// Stateless switch: `checked` stays bound to its source, clicks emit `toggled`.
Rectangle {
    id: root

    property bool checked: false
    property color activeColor: Theme.accentStrong
    signal toggled(bool value)

    function alpha(source, amount) {
        return Qt.rgba(source.r, source.g, source.b, amount);
    }

    implicitWidth: 42
    implicitHeight: 23
    radius: height / 2
    opacity: enabled ? 1 : 0.45
    color: checked ? alpha(activeColor, mouse.containsMouse ? 0.55 : 0.4)
        : mouse.containsMouse ? Theme.surfaceHover : Theme.surface
    border.width: 1
    border.color: checked ? alpha(activeColor, 0.9) : alpha(Theme.border, 0.7)

    Behavior on color { ColorAnimation { duration: 140 } }
    Behavior on border.color { ColorAnimation { duration: 140 } }

    Rectangle {
        id: knob
        y: (parent.height - height) / 2
        x: root.checked ? parent.width - width - 3 : 3
        width: parent.height - 6
        height: width
        radius: height / 2
        color: root.checked ? root.activeColor : Theme.muted

        Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: 140 } }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.toggled(!root.checked)
    }
}
