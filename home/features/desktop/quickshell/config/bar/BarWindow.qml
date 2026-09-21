import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
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
    // Taller than the bar itself so the tint can keep fading past the content.
    // The extra height is deliberately not reserved, and the input mask below
    // keeps it from taking clicks, so it costs no space and steals no input.
    //
    // It has to live on this surface rather than a separate one underneath:
    // Hyprland's workspace blur is a full-monitor blur rect emitted after the
    // background and bottom layers but before windows, and a second one before
    // special-workspace windows. Anything below those gets smeared and no longer
    // lines up with the bar, which renders on the top layer after all of them.
    implicitHeight: Theme.barHeight + Theme.barScrimFade
    exclusiveZone: shown && !hugeMargins ? Theme.barHeight : 0
    color: "transparent"
    WlrLayershell.namespace: "quickshell-bar"
    anchors { top: true; left: true; right: true }
    mask: Region { item: barArea }

    // macOS menu bar treatment: one continuous ramp instead of a flat fill cut
    // off by a hard border line. Strong behind the content, gone by the bottom.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.scrimColor(Theme.barScrimPeak) }
            GradientStop { position: Theme.barScrimContentStop * 0.5; color: Theme.scrimColor(1.12) }
            GradientStop { position: Theme.barScrimContentStop; color: Theme.scrimColor(0.74) }
            GradientStop { position: Theme.barScrimContentStop + (1 - Theme.barScrimContentStop) * 0.32; color: Theme.scrimColor(0.38) }
            GradientStop { position: Theme.barScrimContentStop + (1 - Theme.barScrimContentStop) * 0.64; color: Theme.scrimColor(0.14) }
            GradientStop { position: 1.0; color: Theme.scrimColor(0) }
        }
    }

    // Everything interactive lives here, in the top barHeight of the surface.
    // The mask is bound to this item, so only this strip is clickable.
    Item {
        id: barArea
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: Theme.barHeight

        Workspaces {
            anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
            barScreen: bar.screen
        }

        Media {
            anchors.centerIn: parent
            popupAnchor: barArea
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
            NotificationInbox {
                notificationService: bar.notificationService
                popupAnchor: barArea
            }
            Clock { }
        }
    }
}
