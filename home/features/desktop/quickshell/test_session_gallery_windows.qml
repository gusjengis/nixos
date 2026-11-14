import QtQuick
import Quickshell

ShellRoot {
    FloatingWindow {
        visible: true
        title: "Gallery fixture blue"
        implicitWidth: 600; implicitHeight: 400
        color: "#245da0"
        Text { anchors.centerIn: parent; text: "Blue workspace"; color: "white"; font.pixelSize: 36 }
    }
    FloatingWindow {
        visible: true
        title: "Gallery fixture green"
        implicitWidth: 600; implicitHeight: 400
        color: "#28724a"
        Text { anchors.centerIn: parent; text: "Green workspace"; color: "white"; font.pixelSize: 36 }
    }
}
