import QtQuick
import Quickshell
import "../../theme"

Rectangle {
    id: root

    required property var notificationService
    required property Item popupAnchor
    readonly property bool popupVisible: popup.popupVisible

    function displayTime(date) {
        const hours = date.getHours() % 12 || 12;
        const minutes = ("0" + date.getMinutes()).slice(-2);
        const period = date.getHours() < 12 ? " AM" : " PM";
        return Qt.formatDate(date, "ddd MMM d") + "  " + hours + ":" + minutes + period;
    }

    width: label.implicitWidth + 18
    height: 28
    radius: Theme.radius
    color: mouse.containsMouse || popup.popupVisible ? Theme.barHoverFill : "transparent"

    SystemClock {
        id: clock
        precision: SystemClock.Minutes
    }

    Text {
        id: label
        anchors.centerIn: parent
        text: root.displayTime(clock.date)
        color: Theme.barText
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

    NotificationInbox {
        id: popup
        notificationService: root.notificationService
        popupAnchor: root.popupAnchor
    }
}
