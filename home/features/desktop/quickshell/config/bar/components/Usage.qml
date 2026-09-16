import QtQuick
import "../../theme"

Rectangle {
    id: root

    // Not named "data": that is Item's default property, and shadowing it
    // stops declared children from becoming visual children.
    required property var usage
    required property bool accountBusy
    required property string accountError
    signal refreshRequested()
    signal accountRequested(string profile, bool saved)

    implicitWidth: 28
    implicitHeight: 28
    radius: Theme.radius
    color: mouse.containsMouse || popup.visible ? Theme.surfaceHover : "transparent"

    Text {
        anchors.centerIn: parent
        text: "AI"
        color: Theme.accent
        font { family: Theme.fontFamily; pixelSize: 11; bold: true }
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
