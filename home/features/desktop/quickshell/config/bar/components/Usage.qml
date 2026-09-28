import QtQuick
import QtQuick.Effects
import "../../theme"

Rectangle {
    id: root

    // Not named "data": that is Item's default property, and shadowing it
    // stops declared children from becoming visual children.
    required property var usage
    required property bool accountBusy
    required property string accountError
    readonly property bool popupVisible: popup.visible
    signal refreshRequested()
    signal accountRequested(string profile, bool saved)

    implicitWidth: 28
    implicitHeight: 28
    radius: Theme.radius
    color: hover.hovered ? Theme.barHoverFill : "transparent"

    Image {
        id: aiIcon
        anchors.centerIn: parent
        width: 18
        height: 18
        source: "icons/openai-blossom.svg"
        cache: false
        sourceSize: Qt.size(72, 72)
        fillMode: Image.PreserveAspectFit
        mipmap: true
        layer.enabled: true
        layer.effect: MultiEffect {
            colorization: 1
            colorizationColor: Theme.barText
        }
    }

    HoverHandler {
        id: hover
        blocking: false
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: {
            root.refreshRequested();
            popup.toggle(root);
        }
    }

    UsagePopup {
        id: popup
        usage: root.usage
        accountBusy: root.accountBusy
        accountError: root.accountError
        onAccountRequested: (profile, saved) => root.accountRequested(profile, saved)
    }
}
