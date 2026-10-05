import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.Mpris
import Quickshell.Services.Pipewire
import Quickshell.Widgets
import "../../theme"
import "../../widgets"

// macOS Control Center: the switch.2 menu extra and its module panel.
// Clicking a module's label swaps the panel to that module's detail page
// (Wi-Fi, Bluetooth, Sound), the way macOS expands modules in place.
Rectangle {
    id: root

    required property var controls
    required property Item popupAnchor
    readonly property bool popupVisible: popup.visible

    readonly property var wifi: controls.wifi
    readonly property var bluetooth: controls.bluetooth
    readonly property var bluetoothDevices: bluetooth.devices || []
    readonly property var bluetoothConnected: bluetoothDevices.find(device => device.connected) || null

    readonly property var sink: Pipewire.defaultAudioSink
    readonly property real volume: sink && sink.audio ? sink.audio.volume : 0
    readonly property bool muted: sink && sink.audio ? sink.audio.muted : false

    readonly property var player: {
        const players = Mpris.players.values;
        for (let i = 0; i < players.length; ++i) {
            if (players[i].playbackState === MprisPlaybackState.Playing)
                return players[i];
        }
        return players.length > 0 ? players[0] : null;
    }
    readonly property bool playing: player !== null && player.playbackState === MprisPlaybackState.Playing

    implicitWidth: 30
    implicitHeight: Theme.barItemHeight
    radius: height / 2
    color: popup.visible ? Theme.barHoverFill : "transparent"

    PwObjectTracker { objects: [root.sink] }


    SFSymbol {
        anchors.centerIn: parent
        symbol: "switch.2"
        size: 16
        color: Theme.barText
    }

    MouseArea {
        anchors.fill: parent
        onClicked: popup.toggle(root)
    }

    // Foreground islands share one surface; the compositor supplies their glass.
    component Module: Item {
        id: module
        default property alias content: platterContent.data

        Rectangle {
            anchors.fill: parent
            radius: 32
            color: Theme.background
            visible: !Theme.groupedGlassActive
        }

        Item {
            id: platterContent
            anchors.fill: parent
        }
    }

    component ModuleTitle: Text {
        color: "#ffffff"
        font { family: Theme.fontFamily; pixelSize: 13; weight: Font.DemiBold }
    }

    // One row of the connectivity module: the round button toggles power,
    // the label opens the detail page.
    component ToggleRow: RowLayout {
        id: row

        property string title
        property string subtitle
        property bool on
        property string symbol: ""
        property string glyph: ""
        signal toggled()
        signal opened()

        Layout.fillWidth: true
        spacing: 9

        Rectangle {
            implicitWidth: 36
            implicitHeight: 36
            radius: 18
            color: row.on ? "#ffffff" : Qt.rgba(1, 1, 1, toggleMouse.containsMouse ? 0.24 : 0.16)

            SFSymbol {
                anchors.centerIn: parent
                visible: row.symbol !== ""
                symbol: row.symbol
                size: 18
                color: row.on ? "#007aff" : "#ffffff"
            }

            Text {
                anchors.centerIn: parent
                visible: row.glyph !== ""
                text: row.glyph
                color: row.on ? "#007aff" : "#ffffff"
                font { family: Theme.iconFontFamily; pixelSize: 20 }
            }

            MouseArea {
                id: toggleMouse
                anchors.fill: parent
                hoverEnabled: true
                onClicked: row.toggled()
            }
        }

        Item {
            Layout.fillWidth: true
            implicitHeight: labels.implicitHeight

            ColumnLayout {
                id: labels
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter }
                spacing: 0

                ModuleTitle {
                    Layout.fillWidth: true
                    text: row.title
                    elide: Text.ElideRight
                }

                Text {
                    Layout.fillWidth: true
                    text: row.subtitle
                    color: Qt.rgba(1, 1, 1, 0.85)
                    elide: Text.ElideRight
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    font { family: Theme.fontFamily; pixelSize: 11 }
                }
            }

            MouseArea {
                anchors.fill: parent
                onClicked: row.opened()
            }
        }
    }

    component MediaButton: Item {
        id: button

        property string symbol
        property real size: 14
        property bool active: true
        signal clicked()

        implicitWidth: 24
        implicitHeight: 24

        SFSymbol {
            anchors.centerIn: parent
            symbol: button.symbol
            size: button.size
            color: Theme.text
            opacity: button.active ? (buttonMouse.pressed ? 0.6 : 1) : 0.35
        }

        MouseArea {
            id: buttonMouse
            anchors.fill: parent
            enabled: button.active
            onClicked: button.clicked()
        }
    }

    component DetailHeader: Item {
        signal back()

        Layout.fillWidth: true
        implicitHeight: 20

        RowLayout {
            anchors.fill: parent
            spacing: 4

            SFSymbol {
                symbol: "chevron.left"
                size: 12
                color: Theme.muted
            }

            Text {
                text: "Control Center"
                color: Theme.muted
                font { family: Theme.fontFamily; pixelSize: 12 }
            }

            Item { Layout.fillWidth: true }
        }

        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: parent.back()
        }
    }

    GuardedPopupWindow {
        id: popup
        anchorItem: root

        property string page: "main"

        function toggle(anchorItem) {
            if (visible) {
                visible = false;
                return;
            }
            page = "main";
            popup.anchorItem = anchorItem;
            visible = true;
            root.controls.refresh();
        }

        function open(name) {
            if (name === "wifi")
                wifiPanel.reset();
            if (name === "sound")
                soundPanel.advanced = false;
            page = name;
        }

        function back() {
            if (page === "sound" && soundPanel.advanced)
                soundPanel.advanced = false;
            else if (page !== "main")
                page = "main";
            else
                visible = false;
        }

        // This mapped controller never acquires material or an input region.
        glassNamespace: "quickshell-cc-host"
        backgroundVisible: false
        acceptsInput: false
        shadowPadding: 0
        focusWindows: [popup, mainSurface, details]
        popupX: root.popupAnchor.width
            - (anchorItem ? anchorItem.mapToItem(root.popupAnchor, 0, 0).x : 0)
            - popupWidth - 14
        popupY: Theme.barPopupY(anchorItem) + 11
        popupWidth: 292
        popupHeight: root.controls.brightness.available ? 292 : 216
    }

    GuardedPopupWindow {
        id: mainSurface
        anchorItem: popup.anchorItem
        glassNamespace: "quickshell-cc-group"
        backgroundVisible: false
        focusGrabEnabled: false
        visible: popup.visible && popup.page === "main"
        popupX: popup.popupX
        popupY: popup.popupY
        popupWidth: 292
        popupHeight: popup.popupHeight
        shadowPadding: 80

        ColumnLayout {
            id: mainPage
            visible: popup.page === "main"
            anchors { left: parent.left; right: parent.right; top: parent.top }
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                ColumnLayout {
                    Layout.preferredWidth: 140
                    Layout.preferredHeight: 140
                    spacing: 12

                    Module {
                        id: wifiModule
                        Layout.fillWidth: true
                        implicitHeight: 64

                        ToggleRow {
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
                            title: "Wi-Fi"
                            symbol: "wifi"
                            on: root.wifi.enabled
                            subtitle: !root.wifi.enabled ? "Off" : root.wifi.connected ? root.wifi.connected.ssid : "Not Connected"
                            onToggled: root.controls.wifiPower(!root.wifi.enabled)
                            onOpened: popup.open("wifi")
                        }
                    }

                    Module {
                        id: bluetoothModule
                        Layout.fillWidth: true
                        implicitHeight: 64

                        ToggleRow {
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 14 }
                            title: "Bluetooth"
                            glyph: "󰂯"
                            on: root.bluetooth.powered
                            subtitle: !root.bluetooth.powered ? "Off" : root.bluetoothConnected ? (root.bluetoothConnected.name || "Connected") : "On"
                            onToggled: root.controls.bluetoothPower(!root.bluetooth.powered)
                            onOpened: {
                                popup.open("bluetooth");
                                root.controls.refreshBluetooth();
                            }
                        }
                    }
                }

                // Now Playing
                Module {
                    id: mediaModule
                    Layout.preferredWidth: 140
                    implicitHeight: 140

                    ColumnLayout {
                        id: nowPlaying
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
                        spacing: 8

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 8

                            ClippingRectangle {
                                id: artwork
                                readonly property bool hasArt: root.player !== null && root.player.trackArtUrl !== ""
                                implicitWidth: 40
                                implicitHeight: 40
                                radius: 6
                                color: Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, 0.16)

                                Image {
                                    anchors.fill: parent
                                    visible: artwork.hasArt
                                    source: artwork.hasArt ? root.player.trackArtUrl : ""
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                }

                                Text {
                                    anchors.centerIn: parent
                                    visible: !artwork.hasArt
                                    text: "\uf001"
                                    color: Theme.muted
                                    font { family: Theme.iconFontFamily; pixelSize: 15 }
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0

                                ModuleTitle {
                                    Layout.fillWidth: true
                                    text: root.player ? (root.player.trackTitle || root.player.identity || "Unknown") : "Not Playing"
                                    elide: Text.ElideRight
                                }

                                Text {
                                    Layout.fillWidth: true
                                    visible: text !== ""
                                    text: root.player ? (root.player.trackArtist || root.player.identity || "") : ""
                                    color: Theme.muted
                                    elide: Text.ElideRight
                                    font { family: Theme.fontFamily; pixelSize: 11 }
                                }
                            }
                        }

                        RowLayout {
                            Layout.alignment: Qt.AlignHCenter
                            spacing: 10

                            MediaButton {
                                symbol: "backward.fill"
                                active: root.player !== null && root.player.canGoPrevious
                                onClicked: root.player.previous()
                            }

                            MediaButton {
                                symbol: root.playing ? "pause.fill" : "play.fill"
                                size: 17
                                active: root.player !== null && root.player.canTogglePlaying
                                onClicked: root.player.togglePlaying()
                            }

                            MediaButton {
                                symbol: "forward.fill"
                                active: root.player !== null && root.player.canGoNext
                                onClicked: root.player.next()
                            }
                        }
                    }
                }
            }

            Module {
                id: displayModule
                Layout.fillWidth: true
                visible: root.controls.brightness.available
                implicitHeight: 64

                ColumnLayout {
                    id: displayColumn
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
                    spacing: 4

                    ModuleTitle { text: "Display" }

                    MacSlider {
                        id: brightnessSlider
                        Layout.fillWidth: true
                        thin: true
                        symbol: "sun.min.fill"
                        trailingSymbol: "sun.max.fill"
                        from: 0
                        to: 100
                        stepSize: 1
                        value: root.controls.brightness.percent
                        onPressedChanged: {
                            if (!pressed)
                                root.controls.setBrightness(value);
                        }
                    }

                    Binding {
                        target: brightnessSlider
                        property: "value"
                        value: root.controls.brightness.percent
                        when: !brightnessSlider.pressed
                    }
                }
            }

            Module {
                id: soundModule
                Layout.fillWidth: true
                implicitHeight: 64

                ColumnLayout {
                    id: soundColumn
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
                    spacing: 4

                    Item {
                        Layout.fillWidth: true
                        implicitHeight: soundTitle.implicitHeight

                        RowLayout {
                            id: soundTitle
                            anchors.fill: parent

                            ModuleTitle {
                                Layout.fillWidth: true
                                text: "Sound"
                            }

                            SFSymbol {
                                symbol: "chevron.right"
                                size: 12
                                color: Theme.muted
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            onClicked: popup.open("sound")
                        }
                    }

                    MacSlider {
                        id: volumeSlider
                        Layout.fillWidth: true
                        enabled: !!root.sink && !!root.sink.audio
                        thin: true
                        trailingSymbol: "speaker.wave.3.fill"
                        symbol: root.muted || root.volume <= 0 ? "speaker.slash.fill" : root.volume < 0.34 ? "speaker.wave.1.fill" : root.volume < 0.67 ? "speaker.wave.2.fill" : "speaker.wave.3.fill"
                        onMoved: if (root.sink && root.sink.audio) root.sink.audio.volume = value
                        onSymbolClicked: if (root.sink && root.sink.audio) root.sink.audio.muted = !root.sink.audio.muted
                    }

                    Binding {
                        target: volumeSlider
                        property: "value"
                        value: root.volume
                        when: !volumeSlider.pressed
                        restoreMode: Binding.RestoreNone
                    }
                }
            }
        }

        Shortcut {
            sequence: "Escape"
            enabled: popup.visible && popup.page === "main"
            onActivated: popup.back()
        }
    }

    GuardedPopupWindow {
        id: details

        readonly property Item currentPage: popup.page === "wifi" ? wifiPage : popup.page === "bluetooth" ? bluetoothPage : soundPage
        glassNamespace: "quickshell-cc-detail"
        popupRadius: popup.page === "sound" ? 14 : 13
        focusGrabEnabled: false
        anchorItem: popup.anchorItem
        visible: popup.visible && popup.page !== "main"
        popupX: root.popupAnchor.width
            - (anchorItem ? anchorItem.mapToItem(root.popupAnchor, 0, 0).x : 0)
            - popupWidth - 10
        popupY: Theme.barPopupY(anchorItem) + (popup.page === "sound" ? 5 : 0)
        popupWidth: popup.page === "sound" ? 310 : 340
        popupHeight: Math.min(720, currentPage.implicitHeight + (popup.page === "sound" ? 12 : 24))

        ColumnLayout {
            id: wifiPage
            visible: popup.page === "wifi"
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
            spacing: 8

            DetailHeader { onBack: popup.back() }
            WifiPanel {
                id: wifiPanel
                Layout.fillWidth: true
                controls: root.controls
            }
        }

        ColumnLayout {
            id: bluetoothPage
            visible: popup.page === "bluetooth"
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
            spacing: 8

            DetailHeader { onBack: popup.back() }
            BluetoothPanel {
                Layout.fillWidth: true
                controls: root.controls
            }
        }

        ColumnLayout {
            id: soundPage
            visible: popup.page === "sound"
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 12 }
            spacing: 8

            SoundPanel {
                id: soundPanel
                Layout.fillWidth: true
            }
        }

        Shortcut {
            sequence: "Escape"
            enabled: details.visible
            onActivated: popup.back()
        }
    }
}
