import QtQuick
import Quickshell
import Quickshell.Widgets
import "../../theme"

Rectangle {
    id: row

    required property var entry
    signal activated()

    implicitHeight: entry.isSeparator ? 5 : 28
    radius: Math.max(4, Theme.windowRadius - 8)
    color: !entry.isSeparator && mouse.containsMouse && entry.enabled
        ? Theme.surfaceHover : "transparent"
    opacity: entry.enabled ? 1 : 0.45

    Rectangle {
        visible: row.entry.isSeparator
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
        height: 1
        color: Theme.border
    }

    Rectangle {
        visible: !row.entry.isSeparator && row.entry.buttonType !== QsMenuButtonType.None
        anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
        width: 13
        height: 13
        radius: row.entry.buttonType === QsMenuButtonType.RadioButton ? 7 : 3
        color: row.entry.checkState === Qt.Checked ? Theme.accentStrong : "transparent"
        border.color: row.entry.checkState === Qt.Checked ? Theme.accentStrong : Theme.muted

        Rectangle {
            visible: row.entry.checkState === Qt.Checked
            anchors.centerIn: parent
            width: 5
            height: 5
            radius: 3
            color: Theme.background
        }
    }

    IconImage {
        visible: !row.entry.isSeparator && row.entry.icon !== ""
        anchors { left: parent.left; leftMargin: 5; verticalCenter: parent.verticalCenter }
        implicitSize: 16
        source: row.entry.icon
    }

    Text {
        visible: !row.entry.isSeparator
        anchors {
            left: parent.left
            leftMargin: 27
            right: arrow.left
            rightMargin: 8
            verticalCenter: parent.verticalCenter
        }
        text: row.entry.text.replace(/&/g, "")
        color: Theme.text
        elide: Text.ElideRight
        font { family: Theme.fontFamily; pixelSize: Theme.fontSize }
    }

    Text {
        id: arrow
        visible: !row.entry.isSeparator && row.entry.hasChildren
        anchors { right: parent.right; rightMargin: 7; verticalCenter: parent.verticalCenter }
        text: "›"
        color: Theme.accent
        font { family: Theme.fontFamily; pixelSize: 20; bold: true }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: !row.entry.isSeparator && row.entry.enabled
        onClicked: row.activated()
    }
}
