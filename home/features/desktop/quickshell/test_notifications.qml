import QtQuick
import Quickshell
import Quickshell.Io
import "config/notifications"

ShellRoot {
    NotificationService { id: service }
    Loader {
        id: card
        active: service.history.length > 0
        sourceComponent: NotificationCard {
            visible: false
            entry: service.history[0]
        }
    }

    IpcHandler {
        target: "testNotifications"
        function setDnd(enabled: bool): void { service.doNotDisturb = enabled; }
        function hidePopups(): void {
            for (const entry of service.popups)
                service.hidePopup(entry.key);
        }
        function activate(): void { card.item.activate(); }
        function state(): string {
            return JSON.stringify({
                dnd: service.doNotDisturb,
                history: service.history.map(entry => entry.notification.summary),
                popups: service.popups.map(entry => entry.notification.summary),
                entries: service.entries.length
            });
        }
    }
}
