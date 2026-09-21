import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.Mpris
import Quickshell.Widgets
import "../../theme"
import "../../widgets"

// Basic remote for the Sendspin player (home/features/media/sendspin.nix),
// Music Assistant's own sync-audio protocol. It is a normal MPRIS player
// under the hood (identity "Sendspin"), found the same way Media.qml finds
// any other player, just filtered down to this one specifically so it stays
// reachable even when some other MPRIS source is the one Media.qml is
// currently showing.
GuardedPopupWindow {
    id: popup

    readonly property var sendspinPlayer: {
        const players = Mpris.players.values;
        for (let i = 0; i < players.length; ++i) {
            const identity = players[i].identity || "";
            if (identity.toLowerCase().indexOf("sendspin") !== -1)
                return players[i];
        }
        return null;
    }
    readonly property bool connected: sendspinPlayer !== null
    readonly property bool playing: connected && sendspinPlayer.playbackState === MprisPlaybackState.Playing
    readonly property bool hasProgress: connected && sendspinPlayer.positionSupported && sendspinPlayer.lengthSupported && sendspinPlayer.length > 0
    readonly property real progress: hasProgress ? Math.max(0, Math.min(1, sendspinPlayer.position / sendspinPlayer.length)) : 0
    readonly property int popupWidth: 320

    function toggle(anchorItem) {
        if (visible) {
            visible = false;
            return;
        }
        anchor.item = anchorItem;
        visible = true;
    }

    function formatTime(seconds) {
        if (!seconds || seconds < 0)
            return "0:00";
        const total = Math.floor(seconds);
        const m = Math.floor(total / 60);
        const s = total % 60;
        return m + ":" + (s < 10 ? "0" : "") + s;
    }

    anchor.rect.x: popup.screen.width / 2 - popupWidth / 2
    anchor.rect.y: Theme.barPopupY(anchor.item)
    width: popupWidth
    height: content.implicitHeight + 32
    color: "transparent"

    FrameAnimation {
        running: popup.visible && popup.playing && popup.hasProgress
        onTriggered: popup.sendspinPlayer.positionChanged()
    }

    Rectangle {
        anchors.fill: parent
        radius: Theme.windowRadius
        color: Theme.background
        border {
            width: Theme.windowBorderWidth
            color: Theme.windowBorder
        }
    }

    ColumnLayout {
        id: content
        anchors {
            left: parent.left
            right: parent.right
            top: parent.top
            margins: 16
        }
        spacing: 10

        Text {
            Layout.fillWidth: true
            visible: !popup.connected
            text: "Waiting for the sendspin service to connect to Music Assistant. Check `systemctl --user status sendspin` if this doesn't clear up."
            wrapMode: Text.WordWrap
            color: Theme.muted
            font {
                family: Theme.fontFamily
                pixelSize: Theme.fontSize - 2
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: popup.connected
            spacing: 12

            ClippingRectangle {
                id: artworkTile

                implicitWidth: 56
                implicitHeight: 56
                radius: Theme.radius
                color: Theme.surface

                readonly property bool hasArt: popup.connected && popup.sendspinPlayer.trackArtUrl !== ""

                Image {
                    anchors.fill: parent
                    visible: artworkTile.hasArt
                    source: artworkTile.hasArt ? popup.sendspinPlayer.trackArtUrl : ""
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                }

                Text {
                    anchors.centerIn: parent
                    visible: !artworkTile.hasArt
                    text: "\uf001"
                    color: Theme.muted
                    font {
                        family: Theme.iconFontFamily
                        pixelSize: 22
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2

                Text {
                    Layout.fillWidth: true
                    text: popup.connected ? (popup.sendspinPlayer.trackTitle || "Nothing playing") : ""
                    color: Theme.text
                    elide: Text.ElideRight
                    font {
                        family: Theme.fontFamily
                        pixelSize: Theme.fontSize
                        bold: true
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: popup.connected ? popup.sendspinPlayer.trackArtist : ""
                    color: Theme.muted
                    elide: Text.ElideRight
                    font {
                        family: Theme.fontFamily
                        pixelSize: Theme.fontSize - 2
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: popup.connected ? popup.sendspinPlayer.trackAlbum : ""
                    color: Theme.muted
                    elide: Text.ElideRight
                    font {
                        family: Theme.fontFamily
                        pixelSize: Theme.fontSize - 3
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            visible: popup.connected && popup.hasProgress
            spacing: 4

            ClippingRectangle {
                Layout.fillWidth: true
                implicitHeight: 4
                radius: 2
                color: Qt.rgba(Theme.muted.r, Theme.muted.g, Theme.muted.b, 0.25)

                Rectangle {
                    width: parent.width * popup.progress
                    height: parent.height
                    color: Theme.accent
                }
            }

            RowLayout {
                Layout.fillWidth: true

                Text {
                    text: popup.connected ? popup.formatTime(popup.sendspinPlayer.position) : "0:00"
                    color: Theme.muted
                    font {
                        family: Theme.fontFamily
                        pixelSize: 10
                    }
                }

                Item {
                    Layout.fillWidth: true
                }

                Text {
                    text: popup.connected ? popup.formatTime(popup.sendspinPlayer.length) : "0:00"
                    color: Theme.muted
                    font {
                        family: Theme.fontFamily
                        pixelSize: 10
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.alignment: Qt.AlignHCenter
            visible: popup.connected
            spacing: 10

            Rectangle {
                implicitWidth: 32
                implicitHeight: 32
                radius: Theme.radius
                color: prevMouse.containsMouse ? Theme.surfaceHover : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: "\uf048"
                    color: popup.connected && popup.sendspinPlayer.canGoPrevious ? Theme.text : Theme.muted
                    font {
                        family: Theme.iconFontFamily
                        pixelSize: 16
                    }
                }

                MouseArea {
                    id: prevMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: popup.connected && popup.sendspinPlayer.canGoPrevious
                    cursorShape: Qt.PointingHandCursor
                    onClicked: popup.sendspinPlayer.previous()
                }
            }

            Rectangle {
                implicitWidth: 40
                implicitHeight: 40
                radius: Theme.radius
                color: playMouse.containsMouse ? Theme.surfaceHover : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: popup.playing ? "\uf04c" : "\uf04b"
                    color: Theme.accent
                    font {
                        family: Theme.iconFontFamily
                        pixelSize: 20
                    }
                }

                MouseArea {
                    id: playMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: popup.connected && popup.sendspinPlayer.canTogglePlaying
                    cursorShape: Qt.PointingHandCursor
                    onClicked: popup.sendspinPlayer.togglePlaying()
                }
            }

            Rectangle {
                implicitWidth: 32
                implicitHeight: 32
                radius: Theme.radius
                color: nextMouse.containsMouse ? Theme.surfaceHover : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: "\uf051"
                    color: popup.connected && popup.sendspinPlayer.canGoNext ? Theme.text : Theme.muted
                    font {
                        family: Theme.iconFontFamily
                        pixelSize: 16
                    }
                }

                MouseArea {
                    id: nextMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: popup.connected && popup.sendspinPlayer.canGoNext
                    cursorShape: Qt.PointingHandCursor
                    onClicked: popup.sendspinPlayer.next()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            visible: popup.connected && popup.sendspinPlayer.volumeSupported
            spacing: 8

            Text {
                text: "\uf028"
                color: Theme.muted
                font {
                    family: Theme.iconFontFamily
                    pixelSize: 16
                }
            }

            ThemedSlider {
                id: volumeSlider
                Layout.fillWidth: true
                from: 0
                to: 1
                value: popup.connected ? popup.sendspinPlayer.volume : 0
                onMoved: popup.sendspinPlayer.volume = value

                Binding {
                    target: volumeSlider
                    property: "value"
                    value: popup.connected ? popup.sendspinPlayer.volume : 0
                    when: !volumeSlider.pressed
                }
            }
        }
    }

    Shortcut {
        sequence: "Escape"
        enabled: popup.visible
        onActivated: popup.visible = false
    }
}
