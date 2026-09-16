import QtQuick
import Quickshell

Scope {
    id: root

    required property var notificationService
    required property var notification
    required property int key
    property double receivedAt: Date.now()
    property int revision: 0

    Timer {
        id: refreshTimer
        interval: 0
        onTriggered: root.notificationService.refresh(root)
    }

    Connections {
        target: root.notification

        function onClosed(reason) { root.notificationService.forget(root.key); }
        function onAppNameChanged() { refreshTimer.restart(); }
        function onAppIconChanged() { refreshTimer.restart(); }
        function onSummaryChanged() { refreshTimer.restart(); }
        function onBodyChanged() { refreshTimer.restart(); }
        function onUrgencyChanged() { refreshTimer.restart(); }
        function onExpireTimeoutChanged() { refreshTimer.restart(); }
        function onTransientChanged() { refreshTimer.restart(); }
        function onImageChanged() { refreshTimer.restart(); }
    }
}
