import QtQuick
import QtQuick.Layouts
import Quickshell
import "../theme"
import "components"

PanelWindow {
    id: bar

    required property bool shown
    required property bool hugeMargins
    required property var usage
    required property var refreshUsage
    required property var notificationService

    visible: shown
    implicitHeight: Theme.barHeight
    exclusiveZone: shown && !hugeMargins ? implicitHeight : 0
    color: Theme.background
    anchors { top: true; left: true; right: true }

    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 1
        color: Theme.border
    }

    Workspaces {
        anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
        barScreen: bar.screen
    }

    RowLayout {
        anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
        spacing: Theme.spacing

        Usage {
            usage: bar.usage
            onRefreshRequested: bar.refreshUsage()
        }
        Tray { }
        NotificationInbox { notificationService: bar.notificationService }
        Clock { }
    }
}
