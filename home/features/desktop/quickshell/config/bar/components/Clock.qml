import QtQuick
import Quickshell
import "../../theme"

Rectangle {
    id: root

    function displayTime(date) {
        const hours = date.getHours() % 12 || 12;
        const minutes = ("0" + date.getMinutes()).slice(-2);
        return Qt.formatDate(date, "ddd MMM d") + " " + hours + ":" + minutes;
    }

    width: label.implicitWidth + 18
    height: 28
    radius: Theme.radius
    color: mouse.containsMouse || popup.visible ? Theme.surfaceHover : "transparent"

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.displayTime(clock.date)
        color: Theme.text
        font {
            family: Theme.fontFamily
            pixelSize: Theme.fontSize
            weight: Font.DemiBold
        }
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
