import QtQuick
import Quickshell
import "../../theme"

Rectangle {
    id: root

    function shortTime(date) {
        const hours = date.getHours();
        const minutes = ("0" + date.getMinutes()).slice(-2);
        return (hours % 12 || 12) + ":" + minutes + (hours < 12 ? "a" : "p");
    }

    implicitWidth: label.implicitWidth + 18
    implicitHeight: 28
    radius: Theme.radius
    color: mouse.containsMouse || popup.visible ? Theme.surfaceHover : "transparent"

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.shortTime(clock.date)
        color: Theme.text
        font { family: Theme.fontFamily; pixelSize: Theme.fontSize; bold: true }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: popup.toggle(root)
    }

    CalendarPopup {
        id: popup
        today: clock.date
    }
}
