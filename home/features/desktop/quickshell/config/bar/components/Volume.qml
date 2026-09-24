import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.Pipewire
import "../../theme"
import "../../widgets"

Rectangle {
    id: root

    required property var controls
    readonly property var sink: Pipewire.defaultAudioSink
    readonly property var sourceNode: Pipewire.defaultAudioSource
    readonly property real volume: sink && sink.audio ? sink.audio.volume : 0
    readonly property bool muted: sink && sink.audio ? sink.audio.muted : false
    readonly property bool inputMuted: sourceNode && sourceNode.audio ? sourceNode.audio.muted : false
    readonly property real inputVolume: sourceNode && sourceNode.audio ? sourceNode.audio.volume : 0
    readonly property bool popupVisible: popup.visible

    implicitWidth: 28
    implicitHeight: 28
    radius: Theme.radius
    color: hover.hovered ? Theme.barHoverFill : "transparent"

    function iconText() {
        if (muted || volume <= 0)
            return "󰝟";
        if (volume < 0.5)
            return "󰖀";
        return "󰕾";
    }

    PwObjectTracker { objects: [root.sink, root.sourceNode] }

    Text {
        anchors.centerIn: parent
        text: root.iconText()
        color: root.muted ? Theme.barMuted : Theme.barText
        font { family: Theme.iconFontFamily; pixelSize: 17 }
    }

    HoverHandler {
        id: hover
        blocking: false
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: popup.toggle(root)
        onWheel: event => {
            if (root.sink && root.sink.audio)
                root.sink.audio.volume = Math.max(0, Math.min(1,
                    root.sink.audio.volume + (event.angleDelta.y > 0 ? 0.05 : -0.05)));
        }
    }

    GuardedPopupWindow {
        id: popup

        function toggle(anchorItem) {
            if (visible) {
                visible = false;
                return;
            }
            anchor.item = anchorItem;
            visible = true;
            root.controls.refreshBrightness();
        }

        anchor.rect.x: root.width - width
        anchor.rect.y: Theme.barPopupY(anchor.item)
        implicitWidth: 340
        implicitHeight: content.implicitHeight + 32
        color: "transparent"

        Rectangle {
            anchors.fill: parent
            radius: Theme.windowRadius
            color: Theme.background
            border { width: Theme.windowBorderWidth; color: Theme.windowBorder }
        }

        ColumnLayout {
            id: content
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                Layout.bottomMargin: 2
                spacing: 8

                Text {
                    text: "󰓃"
                    color: Theme.accent
                    font { family: Theme.iconFontFamily; pixelSize: 18 }
                }

                Text {
                    Layout.fillWidth: true
                    text: "Sound"
                    color: Theme.text
                    font { family: Theme.fontFamily; pixelSize: 15; bold: true }
                }

                Text {
                    text: root.sink && root.sink.description ? root.sink.description : ""
                    color: Theme.muted
                    elide: Text.ElideRight
                    maximumLineCount: 1
                    Layout.maximumWidth: 150
                    font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3 }
                }
            }

            // Output
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 54
                radius: Theme.radius + 2
                color: Theme.surface
                border { width: 1; color: Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.5) }

                RowLayout {
                    anchors { fill: parent; leftMargin: 10; rightMargin: 12 }
                    spacing: 10

                    Rectangle {
                        implicitWidth: 32
                        implicitHeight: 32
                        radius: Theme.radius
                        color: outputIconMouse.containsMouse ? Theme.surfaceHover : "transparent"

                        Text {
                            anchors.centerIn: parent
                            text: root.iconText()
                            color: root.muted ? Theme.danger : Theme.accent
                            font { family: Theme.iconFontFamily; pixelSize: 18 }
                        }

                        MouseArea {
                            id: outputIconMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: !!root.sink && !!root.sink.audio
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.sink.audio.muted = !root.sink.audio.muted
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            text: root.muted ? "Output muted" : "Output"
                            color: root.muted ? Theme.danger : Theme.muted
                            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3; bold: true }
                        }

                        ThemedSlider {
                            id: outputSlider
                            Layout.fillWidth: true
                            from: 0
                            to: 1
                            value: root.volume
                            enabled: !!root.sink && !!root.sink.audio
                            fillColor: root.muted ? Theme.muted : Theme.accentStrong
                            onMoved: root.sink.audio.volume = value
                        }

                        Binding {
                            target: outputSlider
                            property: "value"
                            value: root.volume
                            when: !outputSlider.pressed
                        }
                    }

                    Text {
                        Layout.minimumWidth: 38
                        horizontalAlignment: Text.AlignRight
                        text: Math.round(root.volume * 100) + "%"
                        color: root.muted ? Theme.muted : Theme.text
                        font { family: Theme.fontFamily; pixelSize: Theme.fontSize; bold: true }
                    }
                }
            }

            // Input
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 54
                radius: Theme.radius + 2
                color: Theme.surface
                border { width: 1; color: Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.5) }

                RowLayout {
                    anchors { fill: parent; leftMargin: 10; rightMargin: 12 }
                    spacing: 10

                    Rectangle {
                        implicitWidth: 32
                        implicitHeight: 32
                        radius: Theme.radius
                        color: inputIconMouse.containsMouse ? Theme.surfaceHover : "transparent"

                        Text {
                            anchors.centerIn: parent
                            text: root.inputMuted ? "󰍭" : "󰍬"
                            color: root.inputMuted ? Theme.danger : Theme.accent
                            font { family: Theme.iconFontFamily; pixelSize: 18 }
                        }

                        MouseArea {
                            id: inputIconMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            enabled: !!root.sourceNode && !!root.sourceNode.audio
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.sourceNode.audio.muted = !root.sourceNode.audio.muted
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            text: root.inputMuted ? "Microphone muted" : "Microphone"
                            color: root.inputMuted ? Theme.danger : Theme.muted
                            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3; bold: true }
                        }

                        ThemedSlider {
                            id: inputSlider
                            Layout.fillWidth: true
                            from: 0
                            to: 1
                            value: root.inputVolume
                            enabled: !!root.sourceNode && !!root.sourceNode.audio
                            fillColor: root.inputMuted ? Theme.muted : Theme.accentStrong
                            onMoved: root.sourceNode.audio.volume = value
                        }

                        Binding {
                            target: inputSlider
                            property: "value"
                            value: root.inputVolume
                            when: !inputSlider.pressed
                        }
                    }

                    Text {
                        Layout.minimumWidth: 38
                        horizontalAlignment: Text.AlignRight
                        text: Math.round(root.inputVolume * 100) + "%"
                        color: root.inputMuted ? Theme.muted : Theme.text
                        font { family: Theme.fontFamily; pixelSize: Theme.fontSize; bold: true }
                    }
                }
            }

            // Brightness
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 54
                visible: root.controls.brightness.available
                radius: Theme.radius + 2
                color: Theme.surface
                border { width: 1; color: Qt.rgba(Theme.border.r, Theme.border.g, Theme.border.b, 0.5) }

                RowLayout {
                    anchors { fill: parent; leftMargin: 10; rightMargin: 12 }
                    spacing: 10

                    Item {
                        implicitWidth: 32
                        implicitHeight: 32

                        Text {
                            anchors.centerIn: parent
                            text: root.controls.brightness.percent >= 60 ? "󰃠"
                                : root.controls.brightness.percent >= 25 ? "󰃟" : "󰃞"
                            color: Theme.warning
                            font { family: Theme.iconFontFamily; pixelSize: 18 }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2

                        Text {
                            text: "Brightness"
                            color: Theme.muted
                            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3; bold: true }
                        }

                        ThemedSlider {
                            id: brightnessSlider
                            Layout.fillWidth: true
                            from: 0
                            to: 100
                            stepSize: 1
                            value: root.controls.brightness.percent
                            enabled: !root.controls.action.running
                            fillColor: Theme.warning
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

                    Text {
                        Layout.minimumWidth: 38
                        horizontalAlignment: Text.AlignRight
                        text: Math.round(brightnessSlider.value) + "%"
                        color: Theme.text
                        font { family: Theme.fontFamily; pixelSize: Theme.fontSize; bold: true }
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
}
