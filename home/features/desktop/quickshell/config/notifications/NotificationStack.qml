import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import "../theme"

// macOS notification banners: glass cards at the top-right that slide in
// from the screen edge. The surface itself stays transparent; Hyprland blurs
// behind the cards via the quickshell-notifications layer rule.
PanelWindow {
    id: root

    required property var notificationService
    required property bool barShown

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
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; right: true }
    margins { top: (barShown ? Theme.barHeight : 0) + 6 - overhang; right: 10 }
    mask: Region { item: inputArea }

    Item {
        id: inputArea
        x: cards.x
        y: cards.y
        width: root.showing ? cards.width : 0
        height: root.showing ? cards.height : 0
    }

    Column {
        id: cards
        x: root.overhang
        y: root.overhang
        width: parent.width - root.overhang
        spacing: 10
        visible: root.showing

        Repeater {
            model: root.popups

            delegate: NotificationCard {
                id: card
                required property var modelData
                width: cards.width
                entry: modelData
                onDismissRequested: root.notificationService.dismiss(entry.key)

                NumberAnimation on x {
                    from: root.width
                    to: 0
                    duration: 380
                    easing.type: Easing.OutCubic
                }

                Timer {
                    readonly property int baseInterval: root.notificationService.toastTimeout(card.entry)
                    interval: baseInterval + card.entry.revision % 2
                    running: baseInterval > 0 && root.focusedScreen && !cardHover.hovered
                    onTriggered: root.notificationService.hidePopup(card.entry.key)
                }

                HoverHandler { id: cardHover }
            }
        }
    }
}
