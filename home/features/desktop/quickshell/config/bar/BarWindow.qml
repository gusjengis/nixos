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
    required property var openLauncher

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
    readonly property bool popupVisible: media.popupVisible || usage.popupVisible || tray.popupVisible || wifi.popupVisible || battery.popupVisible || controlCenter.popupVisible || clock.popupVisible

    visible: shown || notchFullscreen
    // Wallpaper-dependent scrim is on the bottom layer, below app windows.
    implicitHeight: Theme.barHeight
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

    // Fallback before the wallpaper is known; never tint windows below the bar.
    Rectangle {
        anchors.fill: parent
        visible: !bar.notchFullscreen && Theme.wallpaperPath === ""
        color: Theme.barContentIsDark ? "#55ffffff" : "#55000000"
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

        HoverHandler {
            id: notchReveal
            blocking: false
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

        // Right side, in macOS menu bar order: third-party status items,
        // system status (Wi-Fi, battery), Spotlight, Control Center, clock.
        RowLayout {
            anchors {
                right: parent.right
                rightMargin: 10
                verticalCenter: parent.verticalCenter
            }
            spacing: 4

            Tray {
                id: tray
            }
            Usage {
                id: usage
                usage: bar.usage
                accountBusy: bar.accountBusy
                accountError: bar.accountError
                onRefreshRequested: bar.refreshUsage()
                onAccountRequested: (profile, saved) => bar.accountAction(profile, saved)
            }
            Battery {
                id: battery
                batteryService: bar.battery
            }
            Wifi {
                id: wifi
                controls: bar.systemControls
            }
            Spotlight {
                onActivated: bar.openLauncher()
            }
            ControlCenter {
                id: controlCenter
                controls: bar.systemControls
                popupAnchor: barArea
            }
            Clock {
                id: clock
                notificationService: bar.notificationService
                popupAnchor: barArea
            }
        }
    }
}
