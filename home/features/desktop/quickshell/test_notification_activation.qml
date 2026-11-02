import QtQuick
import Quickshell
import "config/notifications"
import "config/bar/components" as UI

ShellRoot {
    id: root
    property int invoked: 0

    function check(value, message) {
        if (!value) throw new Error(message);
    }

    function cardIn(item) {
        if (typeof item.activate === "function") return item;
        for (const child of item.children || []) {
            const found = cardIn(child);
            if (found) return found;
        }
        return null;
    }

    QtObject {
        id: sourceNotification
        property string appName: "Activation test"
        property string appIcon: ""
        property string image: ""
        property string summary: "Stored notification"
        property string body: ""
        property int urgency: 1
        property var actions: [
            { identifier: "default", text: "Open", invoke: function() { root.invoked++; root.check(!inbox.popupVisible && !service.centerOpen, "Center must release focus before invoking default action"); } },
            { identifier: "reply", text: "Reply", invoke: function() { root.invoked++; root.check(!inbox.popupVisible && !service.centerOpen, "Center must release focus before invoking named action"); } }
        ]
    }
    QtObject {
        id: entry
        property var notification: sourceNotification
        property int key: 1
        property double receivedAt: Date.now()
    }
    QtObject {
        id: service
        property var history: [entry]
        property bool centerOpen: false
    }
    PanelWindow {
        id: host
        implicitWidth: 800
        implicitHeight: 40
        Item { id: anchor; width: 800; height: 30 }
    }
    UI.NotificationInbox {
        id: inbox
        notificationService: service
        popupAnchor: anchor
        compositorGlass: false
    }

    property int stage: 0
    Timer {
        interval: 50
        running: true
        repeat: true
        onTriggered: {
            try {
                if (root.stage === 0) {
                    inbox.toggle(anchor);
                    root.stage++;
                    return;
                }
                if (!inbox.cardWindows.length) return;
                const card = root.cardIn(inbox.cardWindows[0].contentItem);
                if (!card) return;
                if (root.stage === 1) {
                    root.check(inbox.popupVisible && service.centerOpen, "Center did not open");
                    const popup = Array.from(inbox.data).find(item => item.popupWidth !== undefined);
                    const input = popup.mask.item;
                    const inputTop = input.mapToItem(popup.contentItem, 0, 0).y;
                    const cardTop = inbox.cardWindows[0].bodyY - popup.margins.top;
                    root.check(inputTop + input.height <= cardTop,
                        "Transparent host input region overlaps notification card");
                    card.activate();
                    root.check(root.invoked === 1, "Default action was not invoked exactly once");
                    inbox.toggle(anchor);
                    root.stage++;
                    return;
                }
                if (root.stage === 2) {
                    card.invokeAction(sourceNotification.actions[1]);
                    root.check(root.invoked === 2, "Named action was not invoked exactly once");
                    inbox.toggle(anchor);
                    sourceNotification.actions = [];
                    card.activate();
                    root.check(inbox.popupVisible && root.invoked === 2, "Inert notification must not close center");
                    console.log("PASS: center releases focus before default/named actions; inert cards stay open");
                    Qt.quit();
                    root.stage++;
                }
            } catch (error) {
                console.error("FAILED:", error);
                Qt.quit();
                root.stage = 99;
            }
        }
    }
    Timer {
        interval: 5000
        running: true
        onTriggered: { console.error("FAILED: activation fixture timed out"); Qt.quit(); }
    }
}
