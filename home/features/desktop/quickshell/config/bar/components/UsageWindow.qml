import QtQuick
import "../../theme"

Item {
    id: root

    required property var usage
    required property string title
    required property color accentColor

    // null means "no reading", which must not render as 0%.
    readonly property var used: usage && usage.used !== null && usage.used !== undefined
        ? Math.max(0, Math.min(100, usage.used))
        : null

    function resetText(value) {
        if (!value)
            return "Reset time unavailable";
        const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
        const hours = date.getHours();
        const minutes = ("0" + date.getMinutes()).slice(-2);
        const time = (hours % 12 || 12) + ":" + minutes + (hours < 12 ? "a" : "p");
        return "Resets " + Qt.formatDateTime(date, "ddd d MMM, ") + time;
    }

    implicitHeight: 34

    Text {
        anchors { left: parent.left; top: parent.top }
        text: root.title
        color: Theme.text
        font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 1 }
    }

    Text {
        anchors { right: parent.right; top: parent.top }
        text: root.used === null ? "no data" : Math.round(root.used) + "% used"
        color: root.used === null ? Theme.muted : Theme.text
        font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 1; bold: true }
    }

    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 18 }
        height: 5
        radius: 3
        color: Theme.border

        Rectangle {
            width: root.used === null ? 0 : parent.width * root.used / 100
            height: parent.height
            radius: parent.radius
            color: root.accentColor
        }
    }

    Text {
        anchors { left: parent.left; top: parent.top; topMargin: 25 }
        text: root.resetText(root.usage.reset)
        color: Theme.muted
        font { family: Theme.fontFamily; pixelSize: 10 }
    }
}
