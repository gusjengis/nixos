import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import "../theme"

// Legacy transparent layout host; each banner owns its glass layer surface.
PanelWindow {
    id: root

    required property var notificationService
    required property bool barShown
    property bool compositorGlass: Theme.glassActive

    readonly property var popups: notificationService ? notificationService.popups : []
    readonly property var monitor: Hyprland.monitorFor(screen)
    readonly property bool focusedScreen: monitor && Hyprland.focusedMonitor
        && monitor.name === Hyprland.focusedMonitor.name
    // Room left of and above each card for its hover close button.
    readonly property int overhang: 8

    // Stays mapped even with nothing to show: unmapping a layer surface
    // clears Hyprland focus grabs, which would close any open bar popup
    // (and Notification Center itself) whenever a banner came or went.
    visible: focusedScreen
    readonly property bool showing: popups.length > 0 && !notificationService.centerOpen
    implicitWidth: 372 + overhang
    implicitHeight: cards.implicitHeight + overhang
    color: "transparent"
    WlrLayershell.namespace: "quickshell-notifications"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; right: true }
    margins { top: Math.max(overhang, (barShown ? Theme.barHeight : 0) + 6) - overhang; right: 10 }
    mask: Region { width: 0; height: 0 }

    Column {
        id: cards
        x: root.overhang
        y: root.overhang
        width: parent.width - root.overhang
        spacing: 10
        visible: root.showing

        Repeater {
            model: root.popups

            delegate: GlassNotificationCard {
                id: card
                required property var modelData
                width: cards.width
                height: implicitHeight
                entry: modelData
                hostWindow: root
                bodyX: root.screen ? root.screen.width - root.margins.right - root.width + cards.x + x : 0
                bodyY: root.margins.top + cards.y + y
                compositorGlass: root.compositorGlass
                showTimestamp: false
                surfaceVisible: root.showing && root.focusedScreen
                    && bodyY - root.overhang >= 0
                    && root.screen && bodyY + height <= root.screen.height
                    && bodyX - root.overhang >= 0 && bodyX + width <= root.screen.width
                onDismissRequested: root.notificationService.dismiss(entry.key)

                Timer {
                    readonly property int baseInterval: root.notificationService.toastTimeout(card.entry)
                    interval: baseInterval + card.entry.revision % 2
                    running: baseInterval > 0 && root.focusedScreen && !card.hovered
                    onTriggered: root.notificationService.hidePopup(card.entry.key)
                }
            }
        }
    }
}
