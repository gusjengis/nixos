import QtQuick
import Quickshell
import "../../theme"

PopupWindow {
    id: popup

    required property date today

    // Month currently on screen; reset to the live month every time the popup opens.
    property int viewYear: today.getFullYear()
    property int viewMonth: today.getMonth()

    readonly property int cellSize: 32
    readonly property int leadingDays: new Date(viewYear, viewMonth, 1).getDay()

    function toggle(anchorItem) {
        if (visible) {
            visible = false;
            return;
        }
        viewYear = today.getFullYear();
        viewMonth = today.getMonth();
        anchor.item = anchorItem;
        visible = true;
    }

    function shiftMonth(delta) {
        const shifted = new Date(viewYear, viewMonth + delta, 1);
        viewYear = shifted.getFullYear();
        viewMonth = shifted.getMonth();
    }

    function cellDate(index) {
        return new Date(viewYear, viewMonth, 1 - leadingDays + index);
    }

    function isToday(date) {
        return date.getFullYear() === today.getFullYear()
            && date.getMonth() === today.getMonth()
            && date.getDate() === today.getDate();
    }

    // Centered under the trigger instead of right-aligned: the clock sits mid-bar.
    anchor.rect.x: ((anchor.item ? anchor.item.width : 0) - width) / 2
    anchor.rect.y: Theme.barPopupY(anchor.item)
    implicitWidth: content.implicitWidth + 28
    implicitHeight: content.implicitHeight + 28
    color: "transparent"
    grabFocus: true

    Rectangle {
        anchors.fill: parent
        radius: Theme.windowRadius
        color: Theme.background
        border { width: Theme.windowBorderWidth; color: Theme.windowBorder }
    }

    Column {
        id: content
        anchors.centerIn: parent
        spacing: 10

        Item {
            width: grid.width
            height: 26

            Rectangle {
                id: prev
                anchors { left: parent.left; verticalCenter: parent.verticalCenter }
                width: 26
                height: 26
                radius: Theme.radius
                color: prevMouse.containsMouse ? Theme.surfaceHover : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: "‹"
                    color: Theme.text
                    font { family: Theme.fontFamily; pixelSize: 18; bold: true }
                }

                MouseArea {
                    id: prevMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: popup.shiftMonth(-1)
                }
            }

            Text {
                anchors.centerIn: parent
                text: Qt.formatDate(new Date(popup.viewYear, popup.viewMonth, 1), "MMMM yyyy")
                color: Theme.text
                font { family: Theme.fontFamily; pixelSize: 15; bold: true }
            }

            Rectangle {
                id: next
                anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                width: 26
                height: 26
                radius: Theme.radius
                color: nextMouse.containsMouse ? Theme.surfaceHover : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: "›"
                    color: Theme.text
                    font { family: Theme.fontFamily; pixelSize: 18; bold: true }
                }

                MouseArea {
                    id: nextMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: popup.shiftMonth(1)
                }
            }
        }

        Row {
            id: weekdays

            Repeater {
                model: ["S", "M", "T", "W", "T", "F", "S"]

                Text {
                    required property string modelData
                    width: popup.cellSize
                    horizontalAlignment: Text.AlignHCenter
                    text: modelData
                    color: Theme.muted
                    font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2; bold: true }
                }
            }
        }

        Grid {
            id: grid
            columns: 7

            Repeater {
                model: 42

                Item {
                    required property int index
                    readonly property date cell: popup.cellDate(index)
                    readonly property bool inMonth: cell.getMonth() === popup.viewMonth
                    readonly property bool current: popup.isToday(cell)

                    width: popup.cellSize
                    height: popup.cellSize - 2

                    Rectangle {
                        anchors.centerIn: parent
                        width: popup.cellSize - 6
                        height: popup.cellSize - 6
                        radius: width / 2
                        visible: parent.current
                        color: Theme.accent
                    }

                    Text {
                        anchors.centerIn: parent
                        text: parent.cell.getDate()
                        color: parent.current
                            ? Theme.backgroundBase
                            : (parent.inMonth ? Theme.text : Theme.muted)
                        opacity: parent.inMonth ? 1 : 0.45
                        font {
                            family: Theme.fontFamily
                            pixelSize: Theme.fontSize
                            bold: parent.current
                        }
                    }
                }
            }
        }

        Text {
            width: grid.width
            horizontalAlignment: Text.AlignHCenter
            text: Qt.formatDate(popup.today, "dddd d MMMM yyyy")
            color: Theme.muted
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 1 }
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: popup.visible
        onActivated: popup.visible = false
    }
}
