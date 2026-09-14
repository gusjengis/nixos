import QtQuick
import Quickshell
import Quickshell.Services.Notifications

Scope {
    id: root

    readonly property int historyLimit: 50
    readonly property int popupLimit: 3
    property int nextKey: 0
    property var entries: []
    property var history: []
    property var popups: []

    function forget(key) {
        const entry = entries.find(item => item.key === key);
        entries = entries.filter(entry => entry.key !== key);
        history = history.filter(entry => entry.key !== key);
        popups = popups.filter(entry => entry.key !== key);
        if (entry)
            entry.destroy();
    }

    function hidePopup(key) {
        const entry = popups.find(item => item.key === key);
        popups = popups.filter(item => item.key !== key);
        if (entry && entry.notification && entry.notification.transient)
            entry.notification.expire();
    }

    function syncPersistence(entry) {
        history = history.filter(item => item.key !== entry.key);
        if (entry.notification.transient) {
            if (!popups.some(item => item.key === entry.key))
                entry.notification.expire();
        } else {
            addToHistory(entry);
        }
    }

    function refresh(entry) {
        entry.receivedAt = Date.now();
        entry.revision++;
        addPopup(entry);
        syncPersistence(entry);
    }

    function addToHistory(entry) {
        const nextHistory = [entry].concat(history);
        const discarded = nextHistory.slice(historyLimit);
        history = nextHistory.slice(0, historyLimit);
        for (const oldEntry of discarded) {
            if (oldEntry.notification)
                oldEntry.notification.dismiss();
        }
    }

    function addPopup(entry) {
        const nextPopups = [entry].concat(popups.filter(item => item.key !== entry.key));
        const hidden = nextPopups.slice(popupLimit);
        popups = nextPopups.slice(0, popupLimit);
        for (const oldEntry of hidden) {
            if (oldEntry.notification && oldEntry.notification.transient)
                oldEntry.notification.expire();
        }
    }

    function dismiss(key) {
        const entry = history.concat(popups).find(item => item.key === key);
        forget(key);
        if (entry && entry.notification)
            entry.notification.dismiss();
    }

    function clear() {
        const entries = history;
        history = [];
        popups = popups.filter(entry => entry.notification && entry.notification.transient);
        for (const entry of entries) {
            if (entry.notification)
                entry.notification.dismiss();
        }
    }

    function toastTimeout(entry) {
        if (!entry.notification
                || entry.notification.urgency === NotificationUrgency.Critical
                || entry.notification.expireTimeout === 0)
            return 0;
        return entry.notification.expireTimeout > 0
            ? entry.notification.expireTimeout : 5000;
    }

    Component {
        id: entryComponent
        NotificationEntry { }
    }

    NotificationServer {
        id: server
        bodySupported: true
        actionsSupported: true
        imageSupported: true
        persistenceSupported: true
        keepOnReload: true

        onNotification: notification => {
            if (notification.lastGeneration && notification.transient) {
                notification.expire();
                return;
            }

            notification.tracked = true;

            const entry = entryComponent.createObject(root, {
                "key": ++root.nextKey,
                "notification": notification,
                "notificationService": root
            });
            root.entries = root.entries.concat([entry]);

            if (!notification.transient)
                root.addToHistory(entry);

            if (!notification.lastGeneration)
                root.addPopup(entry);
        }
    }
}
