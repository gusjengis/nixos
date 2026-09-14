import QtQuick
import QtQuick.Controls
import "../theme"

TextField {
    id: control

    function alpha(source, amount) {
        return Qt.rgba(source.r, source.g, source.b, amount);
    }

    implicitHeight: 32
    leftPadding: 12
    rightPadding: 12
    topPadding: 0
    bottomPadding: 0
    color: Theme.text
    placeholderTextColor: Theme.muted
    selectionColor: Theme.accentStrong
    selectedTextColor: Theme.backgroundBase
    verticalAlignment: TextInput.AlignVCenter
    font { family: Theme.fontFamily; pixelSize: Theme.fontSize }

    background: Rectangle {
        radius: height / 2
        color: control.alpha(Theme.surfaceBase, 0.75)
        border.width: 1
        border.color: control.activeFocus ? Theme.accentStrong
            : control.hovered ? Theme.border : control.alpha(Theme.border, 0.6)

        Behavior on border.color { ColorAnimation { duration: 120 } }
    }

    cursorDelegate: Rectangle {
        width: 2
        color: Theme.accent
        radius: 1
        visible: control.activeFocus

        SequentialAnimation on opacity {
            loops: Animation.Infinite
            running: control.activeFocus
            NumberAnimation { to: 0; duration: 520; easing.type: Easing.InOutQuad }
            NumberAnimation { to: 1; duration: 520; easing.type: Easing.InOutQuad }
        }
    }
}
