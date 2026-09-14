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
    required property var accountAction
    required property bool accountBusy
    required property string accountError
    required property var battery
    required property var systemControls
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

    Clock {
        anchors { horizontalCenter: parent.horizontalCenter; verticalCenter: parent.verticalCenter }
    }

    RowLayout {
        anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
        spacing: Theme.spacing

        Usage {
            usage: bar.usage
            accountBusy: bar.accountBusy
            accountError: bar.accountError
            onRefreshRequested: bar.refreshUsage()
            onAccountRequested: (profile, saved) => bar.accountAction(profile, saved)
        }
        Tray { }
        Wifi { controls: bar.systemControls }
        Bluetooth { controls: bar.systemControls }
        Volume { controls: bar.systemControls }
        Battery { batteryService: bar.battery }
        NotificationInbox { notificationService: bar.notificationService }
    }
}
