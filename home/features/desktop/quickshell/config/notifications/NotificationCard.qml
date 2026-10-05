import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.Notifications
import Quickshell.Widgets
import "../theme"
import "../widgets"

// macOS notification: a glass card with the app icon on the left, title and
// body, a relative timestamp top-right and any attached image beneath it.
// The close button only appears on hover, overhanging the top-left corner,
// so containers must leave ~8px free above and left of the card.
Item {
    id: root

    required property var entry
    property bool compositorGlass: false
    property bool showTimestamp: true
    readonly property bool hovered: hover.hovered
    signal dismissRequested()

    readonly property var current: entry.notification
    readonly property string appIconSource: current.appIcon ? Quickshell.iconPath(current.appIcon, true) : ""
    // Quickshell falls back to image://icon/<appIcon> when no image was sent;
    // that renders a checkerboard if the icon is missing, so validate it.
    readonly property string imageSource: {
        const image = current.image || "";
        if (!image.startsWith("image://icon/"))
            return image;
        return Quickshell.iconPath(decodeURIComponent(image.slice(13).split("?")[0]), true);
    }
    // With no app icon the attached image stands in for it instead.
    readonly property string iconSource: appIconSource || imageSource
    readonly property string thumbnailSource: appIconSource !== "" && imageSource !== appIconSource ? imageSource : ""
    readonly property bool hasDefaultAction: (current.actions || []).some(action => action.identifier === "default")
    property double now: Date.now()

    function stamp(time) {
        const elapsed = now - time;
        if (elapsed < 60000)
            return "now";
        if (elapsed < 3600000)
            return Math.floor(elapsed / 60000) + "m ago";
        const date = new Date(time);
        const clock = Qt.formatTime(date, "h:mm AP");
        const today = new Date(now);
        if (date.toDateString() === today.toDateString())
            return clock;
        const yesterday = new Date(now - 86400000);
        if (date.toDateString() === yesterday.toDateString())
            return "Yesterday, " + clock;
        return Qt.formatDate(date, "MMM d") + ", " + clock;
    }

    function activate() {
        for (const action of current.actions || []) {
            if (action.identifier === "default") {
                action.invoke();
                return;
            }
        }
    }

    implicitHeight: card.implicitHeight

    Timer {
        interval: 30000
        repeat: true
        running: root.visible
        onTriggered: root.now = Date.now()
    }

    HoverHandler { id: hover; margin: 8 }

    Rectangle {
        id: card

        width: parent.width
        implicitHeight: Math.max(content.implicitHeight, 40) + 24
        radius: 22
        color: root.compositorGlass ? "transparent" : Theme.background
        border { width: root.compositorGlass ? 0 : 1; color: Qt.rgba(1, 1, 1, 0.12) }

        MouseArea {
            anchors.fill: parent
            enabled: root.hasDefaultAction
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: root.activate()
        }

        RowLayout {
            id: content
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 14; rightMargin: 14 }
            spacing: 12

            Item {
                Layout.alignment: Qt.AlignVCenter
                implicitWidth: 36
                implicitHeight: 36

                Rectangle {
                    anchors.fill: parent
                    visible: icon.status !== Image.Ready
                    radius: 9
                    color: Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, 0.16)

                    Text {
                        anchors.centerIn: parent
                        text: (root.current.appName || "?").slice(0, 1).toUpperCase()
                        color: Theme.text
                        font { family: Theme.fontFamily; pixelSize: 17; weight: Font.DemiBold }
                    }
                }

                Image {
                    id: icon
                    anchors.fill: parent
                    source: root.iconSource
                    fillMode: Image.PreserveAspectFit
                    sourceSize { width: 72; height: 72 }
                    visible: status === Image.Ready
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 1

                Text {
                    Layout.fillWidth: true
                    visible: root.current.urgency === NotificationUrgency.Critical
                    text: "TIME SENSITIVE"
                    color: Theme.muted
                    font { family: Theme.fontFamily; pixelSize: 12; weight: Font.DemiBold; letterSpacing: 0.3 }
                }

                Text {
                    Layout.fillWidth: true
                    text: root.current.appName || "Notification"
                    textFormat: Text.PlainText
                    color: Theme.text
                    elide: Text.ElideRight
                    font { family: Theme.fontFamily; pixelSize: 13; weight: Font.DemiBold }
                }

                Text {
                    Layout.fillWidth: true
                    visible: (root.current.summary || "").length > 0
                    text: root.current.summary || root.current.appName || "Notification"
                    textFormat: Text.PlainText
                    color: Theme.text
                    elide: Text.ElideRight
                    font { family: Theme.fontFamily; pixelSize: 14; weight: Font.DemiBold }
                }

                Text {
                    Layout.fillWidth: true
                    visible: text.length > 0
                    text: root.current.body
                    textFormat: Text.PlainText
                    color: Theme.text
                    wrapMode: Text.Wrap
                    maximumLineCount: 4
                    elide: Text.ElideRight
                    font { family: Theme.fontFamily; pixelSize: 14 }
                }

                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: visible ? 6 : 0
                    visible: (root.current.actions || []).some(action => action.identifier !== "default")
                    spacing: 6

                    Repeater {
                        model: root.current.actions || []

                        delegate: Rectangle {
                            required property var modelData
                            visible: modelData.identifier !== "default"
                            width: visible ? actionLabel.implicitWidth + 22 : 0
                            height: visible ? 26 : 0
                            radius: 13
                            color: Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, actionMouse.containsMouse ? 0.2 : 0.12)

                            Text {
                                id: actionLabel
                                anchors.centerIn: parent
                                text: modelData.text
                                color: Theme.text
                                font { family: Theme.fontFamily; pixelSize: 12; weight: Font.Medium }
                            }

                            MouseArea {
                                id: actionMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                onClicked: modelData.invoke()
                            }
                        }
                    }
                }
            }

            ColumnLayout {
                Layout.alignment: Qt.AlignTop
                Layout.fillHeight: true
                spacing: 6

                Text {
                    Layout.alignment: Qt.AlignRight
                    visible: root.showTimestamp
                    text: root.stamp(root.entry.receivedAt)
                    color: Theme.muted
                    font { family: Theme.fontFamily; pixelSize: 12 }
                }

                ClippingRectangle {
                    Layout.alignment: Qt.AlignRight
                    visible: root.thumbnailSource !== "" && thumbnail.status === Image.Ready
                    implicitWidth: 40
                    implicitHeight: 40
                    radius: 8
                    color: "transparent"

                    Image {
                        id: thumbnail
                        anchors.fill: parent
                        source: root.thumbnailSource
                        fillMode: Image.PreserveAspectCrop
                        sourceSize { width: 80; height: 80 }
                    }
                }
            }
        }
    }

    Rectangle {
        x: -7
        y: -7
        width: 22
        height: 22
        radius: 11
        visible: hover.hovered
        color: closeMouse.containsMouse ? Theme.surfaceHoverBase : Theme.surfaceBase
        border { width: 1; color: Qt.rgba(1, 1, 1, 0.16) }

        SFSymbol {
            anchors.centerIn: parent
            symbol: "xmark"
            size: 9
            color: Theme.text
        }

        MouseArea {
            id: closeMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: root.dismissRequested()
        }
    }
}
