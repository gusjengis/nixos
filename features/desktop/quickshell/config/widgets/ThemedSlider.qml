import QtQuick
import QtQuick.Controls
import "../theme"

Slider {
    id: control

    property color fillColor: Theme.accentStrong
    property int trackHeight: 6

    function alpha(source, amount) {
        return Qt.rgba(source.r, source.g, source.b, amount);
    }

    implicitHeight: 22
    implicitWidth: 120
    padding: 0
    focusPolicy: Qt.NoFocus
    hoverEnabled: true
    opacity: enabled ? 1 : 0.45

    background: Rectangle {
        x: control.leftPadding
        y: control.topPadding + control.availableHeight / 2 - height / 2
        width: control.availableWidth
        height: control.trackHeight
        radius: height / 2
        color: control.alpha(Theme.surfaceHoverBase, 0.75)
        border.width: 1
        border.color: control.alpha(Theme.border, 0.6)

        Rectangle {
            width: control.visualPosition * parent.width
            height: parent.height
            radius: parent.radius
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: control.alpha(control.fillColor, 0.65) }
                GradientStop { position: 1; color: control.fillColor }
            }
        }
    }

    handle: Rectangle {
        x: control.leftPadding + control.visualPosition * (control.availableWidth - width)
        y: control.topPadding + control.availableHeight / 2 - height / 2
        implicitWidth: 15
        implicitHeight: 15
        radius: height / 2
        color: control.pressed ? control.fillColor : Theme.text
        border.width: 2
        border.color: control.alpha(control.fillColor, control.hovered || control.pressed ? 1 : 0.7)
        scale: control.pressed ? 1.15 : control.hovered ? 1.08 : 1

        Behavior on scale { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: 110 } }
    }

    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
    }
}
