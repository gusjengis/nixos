import QtQuick
import QtQuick.Effects
import QtQuick.Controls as Controls
import "../../theme"

Rectangle {
    id: root

    required property var provider
    // Fixed brand accents: Claude terracotta and OpenAI green.
    readonly property color accentColor: provider.id === "anthropic" ? "#d97757" : "#10a37f"
    property bool actionable: false
    property var tint: null
    readonly property bool tintHovered: accountMouse.containsMouse
    signal activated()

    // Render whatever numbers exist, including cached ones from a failed
    // refresh. Showing 0% for a failed fetch reads as "no usage", which is a
    // lie; the inline indicator exposes why the numbers are old on hover.
    readonly property bool hasData: provider.windows && provider.windows.length > 0

    function usageWindow(index, label) {
        return root.hasData && provider.windows[index]
            ? provider.windows[index]
            : { "label": label, "used": null, "reset": null };
    }

    implicitHeight: 128
    radius: 12
    color: tint && tint.composited ? "transparent"
        : accountMouse.containsMouse ? (tint ? tint.hover : Theme.cardSurfaceHover) : (tint ? tint.card : Theme.cardSurface)
    border { width: provider.active ? 2 : 1; color: provider.active ? root.accentColor : (root.tint ? root.tint.border : Theme.neutralBorder) }

    MouseArea {
        id: accountMouse
        anchors.fill: parent
        enabled: root.actionable
        hoverEnabled: enabled
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.activated()
    }

    Image {
        id: providerLogo
        anchors { left: parent.left; leftMargin: 12; verticalCenter: providerName.verticalCenter }
        width: 16
        height: 16
        source: root.provider.id === "anthropic" ? "icons/anthropic.svg" : "icons/chatgpt.svg"
        sourceSize: Qt.size(64, 64)
        fillMode: Image.PreserveAspectFit
        mipmap: true
        layer.enabled: true
        layer.effect: MultiEffect {
            colorization: 1
            colorizationColor: root.accentColor
        }
    }

    Text {
        id: providerName
        anchors { left: providerLogo.right; leftMargin: 7; top: parent.top; topMargin: 10 }
        text: root.provider.name
        color: "#f5f5f7"
        font { family: Theme.fontFamily; pixelSize: 14; weight: Font.DemiBold }
    }

    Item {
        anchors { left: providerName.right; leftMargin: 5; verticalCenter: providerName.verticalCenter }
        width: 16
        height: 16
        visible: !!root.provider.error || root.provider.saved === false

        Rectangle {
            anchors.centerIn: parent
            width: 6
            height: 6
            radius: 3
            color: root.hasData ? "#d6b36a" : "#ff6961"
        }

        HoverHandler { id: statusHover }
        Controls.ToolTip.visible: statusHover.hovered
        Controls.ToolTip.delay: 250
        Controls.ToolTip.text: root.provider.saved === false
            ? "Account not saved · click card to save"
            : (root.hasData ? "Stale data · " : "Unavailable · ") + root.provider.error
    }

    Column {
        anchors {
            left: parent.left
            right: parent.right
            top: providerName.bottom
            leftMargin: 12
            rightMargin: 12
            topMargin: 8
        }
        spacing: 8

        UsageWindow {
            width: parent.width
            usage: root.usageWindow(0, "5h")
            title: "5-hour window"
            accentColor: root.accentColor
        }

        UsageWindow {
            width: parent.width
            usage: root.usageWindow(1, "7d")
            title: "Weekly window"
            accentColor: root.accentColor
        }
    }
}
