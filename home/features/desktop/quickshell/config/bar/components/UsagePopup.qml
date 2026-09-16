import QtQuick
import Quickshell
import "../../theme"

GuardedPopupWindow {
    id: popup

    required property var usage
    required property bool accountBusy
    required property string accountError
    signal accountRequested(string profile, bool saved)

    function provider(id, name) {
        const providers = usage.providers || [];
        return providers.find(item => item.id === id)
            || { "id": id, "name": name, "available": false, "error": "loading", "windows": [] };
    }

    function toggle(anchorItem) {
        if (visible) {
            visible = false;
            return;
        }
        anchor.item = anchorItem;
        visible = true;
    }

    anchor.rect.x: (anchor.item ? anchor.item.width : 0) - width
    anchor.rect.y: Theme.barPopupY(anchor.item)
    implicitWidth: 390
    implicitHeight: 481
    color: "transparent"

    Rectangle {
        anchors.fill: parent
        radius: Theme.windowRadius
        color: Theme.background
        border { width: Theme.windowBorderWidth; color: Theme.windowBorder }
    }

    Column {
        anchors { fill: parent; margins: 14 }
        spacing: 10

        Text {
            text: "AI usage"
            color: Theme.text
            font { family: Theme.fontFamily; pixelSize: 16; bold: true }
        }

        Text {
            text: popup.accountError || "Subscription limits"
            color: popup.accountError ? Theme.danger : Theme.muted
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 1 }
        }

        UsageProvider {
            width: parent.width
            provider: popup.provider("anthropic", "Anthropic")
            accentColor: Theme.warning
        }

        UsageProvider {
            id: personalCard
            width: parent.width
            provider: popup.provider("openai-personal", "OpenAI · Personal")
            accentColor: Theme.accentStrong
            actionable: !popup.accountBusy
            onActivated: popup.accountRequested("personal", personalCard.provider.saved === true)
        }

        UsageProvider {
            id: businessCard
            width: parent.width
            provider: popup.provider("openai-business", "OpenAI · Business")
            accentColor: Theme.accentStrong
            actionable: !popup.accountBusy
            onActivated: popup.accountRequested("business", businessCard.provider.saved === true)
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: popup.visible
        onActivated: popup.visible = false
    }
}
