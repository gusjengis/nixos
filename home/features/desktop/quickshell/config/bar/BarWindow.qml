import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import "../theme"
import "components"

PanelWindow {
    id: bar

    required property bool shown
    required property string notchMonitor
    required property bool hugeMargins
    required property var usage
    required property var refreshUsage
    required property var accountAction
    required property bool accountBusy
    required property string accountError
    required property var battery
    required property var systemControls
    required property var notificationService

    readonly property var monitor: Hyprland.monitorFor(screen)
    readonly property var activeWorkspace: monitor ? monitor.activeWorkspace : null
    readonly property bool notchDisplay: notchMonitor !== "" && monitor && monitor.name === notchMonitor
    // The client has to believe it is fullscreen *and* the compositor has to be
    // filling the screen with it. A client can report itself fullscreen while
    // the compositor shows it normally, and keying on that alone blacks out the
    // notch for windows that are not covering it. Any non-zero compositor state
    // counts, because the window is briefly true fullscreen before the internal
    // display's translation to maximized lands.
    readonly property bool notchFullscreen: notchDisplay && activeWorkspace && activeWorkspace.toplevels.values.some(toplevel => {
        const state = toplevel.lastIpcObject;
        return state && state.fullscreen > 0 && state.fullscreenClient === 2;
    })
    readonly property bool popupVisible: media.popupVisible || usage.popupVisible || tray.popupVisible || wifi.popupVisible || bluetooth.popupVisible || volume.popupVisible || battery.popupVisible || clock.popupVisible

    visible: shown || notchFullscreen
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
    // The notch is dead screen, so it is reserved unconditionally on that panel
    // rather than only once a fullscreen window is detected. Reserving on
    // detection is circular: the fullscreen geometry is computed from the
    // reserved area, so the window is sized before the reservation exists and
    // ends up under the notch. Huge margins still suppress the reservation on
    // ordinary displays, where the bar is meant to overlay.
    exclusiveZone: notchDisplay || (shown && !hugeMargins) ? Theme.barHeight : 0
    color: "transparent"
    WlrLayershell.namespace: "quickshell-bar"
    anchors {
        top: true
        left: true
        right: true
    }
    mask: Region {
        item: barArea
    }

    // macOS menu bar treatment: one continuous ramp instead of a flat fill cut
    // off by a hard border line. Strong behind the content, gone by the bottom.
    Rectangle {
        anchors.fill: parent
        visible: !bar.notchFullscreen
        gradient: Gradient {
            GradientStop {
                position: 0.0
                color: Theme.scrimColor(Theme.barScrimPeak)
            }
            GradientStop {
                position: Theme.barScrimContentStop * 0.5
                color: Theme.scrimColor(1.12)
            }
            GradientStop {
                position: Theme.barScrimContentStop
                color: Theme.scrimColor(0.74)
            }
            GradientStop {
                position: Theme.barScrimContentStop + (1 - Theme.barScrimContentStop) * 0.32
                color: Theme.scrimColor(0.38)
            }
            GradientStop {
                position: Theme.barScrimContentStop + (1 - Theme.barScrimContentStop) * 0.64
                color: Theme.scrimColor(0.14)
            }
            GradientStop {
                position: 1.0
                color: Theme.scrimColor(0)
            }
        }
    }

    Rectangle {
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
        }
        height: Theme.barHeight
        color: "black"
        visible: bar.notchFullscreen
    }

    // Everything interactive lives here, in the top barHeight of the surface.
    // The mask is bound to this item, so only this strip is clickable.
    Item {
        id: barArea
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
        }
        height: Theme.barHeight
        opacity: !bar.notchFullscreen || notchReveal.hovered || bar.popupVisible ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: 120
            }
        }

        Workspaces {
            anchors {
                left: parent.left
                leftMargin: 10
                verticalCenter: parent.verticalCenter
            }
            barScreen: bar.screen
        }

        Media {
            id: media
            anchors.centerIn: parent
            popupAnchor: barArea
            visible: false
        }

        RowLayout {
            anchors {
                right: parent.right
                rightMargin: 10
                verticalCenter: parent.verticalCenter
            }
            spacing: Theme.spacing

            Usage {
                id: usage
                usage: bar.usage
                accountBusy: bar.accountBusy
                accountError: bar.accountError
                onRefreshRequested: bar.refreshUsage()
                onAccountRequested: (profile, saved) => bar.accountAction(profile, saved)
            }
            Tray {
                id: tray
            }
            Wifi {
                id: wifi
                controls: bar.systemControls
            }
            Bluetooth {
                id: bluetooth
                controls: bar.systemControls
            }
            Volume {
                id: volume
                controls: bar.systemControls
            }
            Battery {
                id: battery
                batteryService: bar.battery
            }
            Clock {
                id: clock
                notificationService: bar.notificationService
                popupAnchor: barArea
            }
        }
    }

    Item {
        anchors {
            top: parent.top
            left: parent.left
            right: parent.right
        }
        height: Theme.barHeight
        z: 1

        HoverHandler {
            id: notchReveal
        }
    }
}
