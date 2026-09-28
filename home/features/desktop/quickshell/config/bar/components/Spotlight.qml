import QtQuick
import "../../theme"
import "../../widgets"

// Spotlight menu extra; opens the app launcher.
Rectangle {
    id: root

    signal activated()

    implicitWidth: 30
    implicitHeight: 24
    radius: 6
    color: mouse.pressed ? Theme.barHoverFill : "transparent"

    SFSymbol {
        anchors.centerIn: parent
        symbol: "magnifyingglass"
        size: 15
        color: Theme.barText
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        onClicked: root.activated()
    }
}
