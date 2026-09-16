import QtQuick
import QtQuick.Controls
import "../theme"

ScrollBar {
    id: control

    function alpha(source, amount) {
        return Qt.rgba(source.r, source.g, source.b, amount);
    }

    policy: ScrollBar.AsNeeded
    implicitWidth: 6
    padding: 0

    contentItem: Rectangle {
        implicitWidth: 6
        radius: width / 2
        color: control.pressed ? Theme.accentStrong
            : control.hovered ? Theme.accent : control.alpha(Theme.muted, 0.55)
        opacity: control.policy === ScrollBar.AlwaysOn || control.active ? 1 : 0

        Behavior on opacity { NumberAnimation { duration: 180 } }
        Behavior on color { ColorAnimation { duration: 120 } }
    }

    background: Item { }
}
