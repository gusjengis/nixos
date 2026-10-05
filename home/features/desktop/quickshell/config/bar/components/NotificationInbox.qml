import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import Quickshell
import "../../notifications"
import "../../theme"
import "../../widgets"

// Transparent scrolling host; cards own independent glass layer surfaces.
Item {
    id: root

    required property var notificationService
    required property Item popupAnchor
    property bool compositorGlass: Theme.glassActive
    property var cardWindows: []
    readonly property var history: notificationService ? notificationService.history : []
    readonly property bool popupVisible: popup.visible
    // Room left of and above each card for its hover close button.
    readonly property int overhang: 8

    function registerCard(window) {
        cardWindows = cardWindows.concat([window]);
    }

    function unregisterCard(window) {
        cardWindows = cardWindows.filter(item => item !== window);
    }

    function scrollCards(delta) {
        const minY = list.originY - list.topMargin;
        const maxY = Math.max(minY, list.originY + list.contentHeight + list.bottomMargin - list.height);
        list.contentY = Math.max(minY, Math.min(maxY, list.contentY - delta));
    }

    function toggle(anchorItem) {
        if (popup.visible) {
            popup.visible = false;
            return;
        }
        popup.anchorItem = anchorItem;
        popup.visible = true;
    }


    GuardedPopupWindow {
        id: popup

        readonly property real maxListHeight: (screen ? screen.height : 1000) - Theme.barHeight - header.height - 60

        // Transparent surface: only the cards carry material.
        glassNamespace: "quickshell-inbox"
        backgroundVisible: false
        shadowPadding: 0
        focusWindows: [popup].concat(root.cardWindows)
        popupX: root.popupAnchor.width
            - (anchorItem ? anchorItem.mapToItem(root.popupAnchor, 0, 0).x : 0)
            - popupWidth - 10
        popupWidth: 380
        popupHeight: header.height + 10 + (root.history.length > 0 ? list.height : empty.implicitHeight + 8)
        onVisibleChanged: root.notificationService.centerOpen = visible

        RowLayout {
            id: header
            anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: root.overhang + 6 }
            height: 40

            Text {
                Layout.fillWidth: true
                text: "Notification Center"
                color: Theme.barText
                font { family: Theme.fontFamily; pixelSize: 22; weight: Font.DemiBold }
                layer.enabled: !Theme.barContentIsDark
                layer.effect: MultiEffect {
                    shadowEnabled: true
                    shadowColor: "#000000"
                    shadowOpacity: 0.35
                    shadowBlur: 0.4
                    shadowVerticalOffset: 1
                }
            }

            Rectangle {
                visible: root.history.length > 0
                implicitWidth: 28
                implicitHeight: 28
                radius: 14
                color: clearMouse.containsMouse ? Theme.surfaceHover : Theme.background
                border { width: 1; color: Qt.rgba(1, 1, 1, 0.12) }

                SFSymbol {
                    anchors.centerIn: parent
                    symbol: "xmark"
                    size: 11
                    color: Theme.text
                }

                MouseArea {
                    id: clearMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: root.notificationService.clear()
                }
            }
        }

        Text {
            id: empty
            anchors { left: header.left; top: header.bottom; topMargin: 4 }
            visible: root.history.length === 0
            text: "No Notifications"
            color: Theme.barMuted
            font { family: Theme.fontFamily; pixelSize: 14 }
        }

        ListView {
            id: list
            anchors { left: parent.left; right: parent.right; top: header.bottom; topMargin: 10 - root.overhang }
            height: Math.min(contentHeight + topMargin + bottomMargin, popup.maxListHeight)
            visible: root.history.length > 0
            topMargin: root.overhang
            leftMargin: root.overhang
            spacing: 10
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.history

            // Layer windows cannot inherit Item clipping. Hide any card whose
            // body/close overhang is not wholly in the viewport; partial rows
            // leave an edge gap instead of floating over the header or desktop.
            delegate: GlassNotificationCard {
                id: card
                required property var modelData
                width: list.width - root.overhang
                height: implicitHeight
                entry: modelData
                hostWindow: popup
                bodyX: popup._origin.x + list.x + x - list.contentX
                bodyY: popup._origin.y + list.y + y - list.contentY
                compositorGlass: root.compositorGlass
                keyboardEnabled: true
                surfaceVisible: list.visible && y - list.contentY - root.overhang >= 0
                    && y - list.contentY + height <= list.height
                    && popup.screen && bodyY + height <= popup.screen.height
                    && bodyY - root.overhang >= 0
                    && bodyX - root.overhang >= 0 && bodyX + width <= popup.screen.width
                Component.onCompleted: root.registerCard(window)
                Component.onDestruction: root.unregisterCard(window)
                onDismissRequested: root.notificationService.dismiss(entry.key)
                onCloseRequested: popup.visible = false
                onScrollRequested: delta => root.scrollCards(delta)
            }
        }

        Shortcut {
            sequence: "Escape"
            enabled: popup.visible
            onActivated: popup.visible = false
        }
    }
}
