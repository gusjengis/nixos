import QtQuick
import Quickshell
import Quickshell.Io
import "config/notifications"

ShellRoot {
    NotificationService { id: service }

    IpcHandler {
        target: "testNotifications"
        function setDnd(enabled: bool): void { service.doNotDisturb = enabled; }
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
