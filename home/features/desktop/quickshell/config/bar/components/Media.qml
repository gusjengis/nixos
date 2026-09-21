import QtQuick
import QtQuick.Layouts
import QtQml.Models
import Quickshell
import Quickshell.Services.Mpris
import Quickshell.Widgets
import "../../theme"

ClippingRectangle {
    id: root

    required property Item popupAnchor
    property var player: null
    readonly property bool playing: player && player.playbackState === MprisPlaybackState.Playing
    readonly property bool hasProgress: player && player.positionSupported && player.lengthSupported && player.length > 0
    readonly property real progress: hasProgress ? Math.max(0, Math.min(1, player.position / player.length)) : 0

    readonly property bool hasTrack: player !== null && player.trackTitle !== ""

    visible: hasTrack
    implicitWidth: 380
    implicitHeight: 30
    radius: Theme.radius + 2
    color: hover.hovered || popup.visible ? Theme.surfaceHover : Theme.surface
    border { width: 1; color: Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.55) }

    function selectPlayer() {
        const players = Mpris.players.values;
        for (let i = 0; i < players.length; ++i) {
            if (players[i].playbackState === MprisPlaybackState.Playing) {
                root.player = players[i];
                return;
            }
        }
        root.player = players.length > 0 ? players[0] : null;
    }

    Instantiator {
        model: Mpris.players

        Connections {
            required property var modelData
            target: modelData

            Component.onCompleted: {
                if (!root.player || modelData.playbackState === MprisPlaybackState.Playing)
                    root.player = modelData;
            }

            Component.onDestruction: {
                if (root.player === modelData) {
                    root.player = null;
                    Qt.callLater(root.selectPlayer);
                }
            }

            function onPlaybackStateChanged() {
                if (modelData.playbackState === MprisPlaybackState.Playing)
                    root.player = modelData;
            }
        }
    }

    HoverHandler { id: hover }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: popup.toggle(root.popupAnchor)
    }

    MediaPopup {
        id: popup
    }

    FrameAnimation {
        running: root.playing && root.hasProgress
        onTriggered: root.player.positionChanged()
    }

    RowLayout {
        anchors.centerIn: parent
        width: Math.min(implicitWidth, parent.width - 12)
        spacing: 5

        Text {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            text: root.player ? (root.player.trackTitle || root.player.identity || "Unknown track") : ""
            color: Theme.text
            elide: Text.ElideRight
            maximumLineCount: 1
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2; weight: Font.DemiBold }
        }

        Text {
            text: "•"
            visible: root.player && root.player.trackArtist !== ""
            color: Theme.muted
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2; weight: Font.DemiBold }
        }

        Text {
            text: root.player ? root.player.trackArtist : ""
            color: Theme.text
            horizontalAlignment: Text.AlignRight
            maximumLineCount: 1
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2; weight: Font.DemiBold }
        }
    }

    ClippingRectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 1 }
        height: 2
        radius: 1
        visible: root.hasProgress
        color: Qt.rgba(Theme.muted.r, Theme.muted.g, Theme.muted.b, 0.25)

        Rectangle {
            width: parent.width * root.progress
            height: parent.height
            color: Theme.accent
        }
    }

}
