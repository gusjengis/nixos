import QtQuick
import Quickshell
import Quickshell.Hyprland
import Quickshell.Services.Notifications
import "../theme"

PanelWindow {
    id: root

    required property var notificationService
    required property bool barShown

    readonly property var popups: notificationService ? notificationService.popups : []
    readonly property var monitor: Hyprland.monitorFor(screen)
    readonly property bool focusedScreen: monitor && Hyprland.focusedMonitor
        && monitor.name === Hyprland.focusedMonitor.name

    visible: focusedScreen && popups.length > 0
    implicitWidth: 380
    implicitHeight: cards.implicitHeight
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; right: true }
    margins { top: barShown ? Theme.barHeight + 8 : 8; right: 8 }

    Column {
        id: cards
        width: parent.width
        spacing: 8

        Repeater {
            model: root.popups

            delegate: NotificationCard {
                id: card
                required property var modelData
                width: cards.width
                entry: modelData
                onDismissRequested: root.notificationService.dismiss(entry.key)

                Timer {
                    id: expiryTimer
                    readonly property int baseInterval: root.notificationService.toastTimeout(card.entry)
                    interval: baseInterval + card.entry.revision % 2
                    running: baseInterval > 0 && root.focusedScreen && !hover.hovered
                    onTriggered: root.notificationService.hidePopup(card.entry.key)
                }

                HoverHandler { id: hover }
            }
        }
    }
}
