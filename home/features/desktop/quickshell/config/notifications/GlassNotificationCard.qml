import QtQuick
import Quickshell

// Layout-only delegate; content and hover live in the independent card window.
Item {
    id: root

    required property var entry
    required property var hostWindow
    property real bodyX: 0
    property real bodyY: 0
    property bool surfaceVisible: true
    property bool compositorGlass: false
    property bool showTimestamp: true
    property bool keyboardEnabled: false
    readonly property bool hovered: card.hovered
    readonly property NotificationSurface window: surface
    signal dismissRequested()
    signal closeRequested()
    signal scrollRequested(real delta)

    implicitHeight: measurement.implicitHeight

    // Measure in the layout host, independently of the card window's visibility.
    // Viewport clipping must not change the height used to decide visibility.
    NotificationCard {
        id: measurement
        width: root.width
        opacity: 0
        enabled: false
        entry: root.entry
        compositorGlass: true
        showTimestamp: root.showTimestamp
    }

    NotificationSurface {
        id: surface
        screen: root.hostWindow.screen
        bodyX: root.bodyX
        bodyY: root.bodyY
        bodyWidth: root.width
        bodyHeight: root.height
        keyboardEnabled: root.keyboardEnabled
        visible: root.hostWindow.visible && root.surfaceVisible
            && bodyWidth > 0 && bodyHeight > 0

        NotificationCard {
            id: card
            anchors.fill: parent
            entry: root.entry
            compositorGlass: root.compositorGlass
            showTimestamp: root.showTimestamp
            onDismissRequested: root.dismissRequested()
        }

        // Card windows cover the ListView: forward wheel input to its owner.
        WheelHandler {
            enabled: root.keyboardEnabled
            onWheel: event => root.scrollRequested(event.angleDelta.y !== 0
                ? event.angleDelta.y / 3 : event.pixelDelta.y)
        }

        DragHandler {
            enabled: root.keyboardEnabled
            target: null
            xAxis.enabled: false
            property real previousY: 0
            onActiveChanged: previousY = activeTranslation.y
            onActiveTranslationChanged: {
                const delta = activeTranslation.y - previousY;
                previousY = activeTranslation.y;
                if (active)
                    root.scrollRequested(delta);
            }
        }

        Shortcut {
            sequence: "Escape"
            enabled: surface.visible && root.keyboardEnabled
            onActivated: root.closeRequested()
        }
    }
}
