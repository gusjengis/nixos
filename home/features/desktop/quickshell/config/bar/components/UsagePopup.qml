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
        popup.anchorItem = anchorItem;
        visible = true;
    }

    popupX: (anchorItem ? anchorItem.width : 0) - popupWidth
    popupWidth: 390
    popupHeight: content.implicitHeight + 32
    backgroundVisible: false
    glassNamespace: Theme.desktopTintComposited ? "quickshell-usage" : "quickshell-menu"

    WallpaperTint {
        id: usageTint
        screen: popup.screen
        region: Qt.rect(popup._origin.x, popup._origin.y, popup.popupWidth, popup.popupHeight)
        enabled: popup.visible
        composited: neutralCards.active
    }

    NeutralSurfaces {
        id: neutralCards
        namespace: popup.glassNamespace
        enabled: popup.visible
        radius: popup.popupRadius
        rectangles: [anthropicCard, personalCard, businessCard].map(card => ({
            x: content.x + card.x, y: content.y + card.y,
            width: card.width, height: card.height, radius: card.radius, hovered: card.tintHovered
        }))
    }

    // Compositor glass and opaque content-background tint are separate materials.
    Rectangle {
        anchors.fill: parent
        visible: !popup.glass
        radius: popup.popupRadius
        color: usageTint.surface
        border { width: 1; color: "#545457" }
    }

    Column {
        id: content
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
        spacing: 8

        Column {
            width: parent.width
            spacing: 4

            Text {
                text: "AI Usage"
                color: "#f5f5f7"
                font { family: Theme.fontFamily; pixelSize: 17; weight: Font.DemiBold }
            }

            Text {
                width: parent.width
                text: popup.accountError || "Subscription limits"
                wrapMode: Text.Wrap
                color: popup.accountError ? "#ff6961" : "#aeaeb2"
                font { family: Theme.fontFamily; pixelSize: 12 }
            }
        }

        UsageProvider {
            id: anthropicCard
            width: parent.width
            provider: popup.provider("anthropic", "Anthropic")
            tint: usageTint
        }

        UsageProvider {
            id: personalCard
            width: parent.width
            provider: popup.provider("openai-personal", "OpenAI · Personal")
            tint: usageTint
            actionable: !popup.accountBusy
            onActivated: popup.accountRequested("personal", personalCard.provider.saved === true)
        }

        UsageProvider {
            id: businessCard
            width: parent.width
            provider: popup.provider("openai-business", "OpenAI · Business")
            tint: usageTint
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
