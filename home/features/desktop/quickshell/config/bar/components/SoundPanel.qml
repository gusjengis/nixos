import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.Pipewire
import Quickshell.Widgets
import "../../theme"
import "../../widgets"

// Output-first Sound module; input and application mixing live in Settings.
ColumnLayout {
    id: panel

    property bool advanced: false
    readonly property var sink: Pipewire.defaultAudioSink
    readonly property var source: Pipewire.defaultAudioSource
    readonly property var nodes: Pipewire.nodes.values.filter(node => node.audio)
    readonly property var sinks: nodes.filter(node => !node.isStream && node.isSink)
    readonly property var sources: nodes.filter(node => !node.isStream && !node.isSink)
    // Quickshell flags playback streams as sinks (Stream/Output/Audio).
    readonly property var streams: nodes.filter(node => node.isStream && node.isSink)

    function label(node) {
        return node.nickname || node.description || node.name;
    }

    function appLabel(node) {
        const props = node.properties || {};
        return props["application.name"] || node.description || node.name;
    }

    function deviceSymbol(node) {
        if (!node.isSink)
            return "mic.fill";
        const props = node.properties || {};
        const text = [node.name, node.description, node.nickname, props["device.form-factor"]].join(" ").toLowerCase();
        if (/hdmi|displayport|\btv\b/.test(text))
            return "display";
        if (/headphone|headset|hpa|buds|airpod|bluez/.test(text))
            return "headphones";
        return "speaker.wave.2.fill";
    }

    function volumeSymbol(audio) {
        if (!audio || audio.muted || audio.volume <= 0)
            return "speaker.slash.fill";
        return audio.volume < 0.34 ? "speaker.wave.1.fill" : audio.volume < 0.67 ? "speaker.wave.2.fill" : "speaker.wave.3.fill";
    }

    spacing: 6

    PwObjectTracker { objects: panel.nodes }

    // Slider bound to a node's volume that does not fight the user mid-drag.
    component NodeSlider: MacSlider {
        id: slider

        property var node: null
        property bool input: false
        readonly property var audio: node ? node.audio : null

        Layout.fillWidth: true
        enabled: !!audio
        symbol: input ? (audio && audio.muted ? "mic.slash.fill" : "mic.fill") : panel.volumeSymbol(audio)
        onMoved: if (audio) audio.volume = value
        onSymbolClicked: if (audio) audio.muted = !audio.muted

        Binding {
            target: slider
            property: "value"
            value: slider.audio ? slider.audio.volume : 0
            when: !slider.pressed
            restoreMode: Binding.RestoreNone
        }
    }

    component SectionLabel: Text {
        Layout.fillWidth: true
        Layout.topMargin: 8
        color: Theme.menuSecondaryText
        font { family: Theme.fontFamily; pixelSize: 12; weight: Font.DemiBold }
    }

    // Selected output uses a white badge and blue glyph, as in macOS.
    component DeviceRow: Rectangle {
        id: row

        required property var modelData
        property bool selected
        signal picked()

        Layout.fillWidth: true
        implicitHeight: 32
        radius: 8
        color: rowMouse.containsMouse ? Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, 0.08) : "transparent"

        RowLayout {
            anchors { fill: parent; leftMargin: 4; rightMargin: 8 }
            spacing: 9

            Rectangle {
                implicitWidth: 26
                implicitHeight: 26
                radius: 13
                color: row.selected ? "#ffffff" : Qt.rgba(1, 1, 1, 0.22)

                SFSymbol {
                    anchors.centerIn: parent
                    symbol: panel.deviceSymbol(row.modelData)
                    size: 12
                    color: row.selected ? Theme.menuHighlight : "#ffffff"
                }
            }

            Text {
                Layout.fillWidth: true
                text: panel.label(row.modelData)
                color: Theme.menuText
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: 13 }
            }
        }

        MouseArea {
            id: rowMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: row.picked()
        }
    }

    Text {
        text: panel.advanced ? "Sound Settings" : "Sound"
        color: Theme.menuText
        font { family: Theme.fontFamily; pixelSize: 13; weight: Font.DemiBold }
    }

    NodeSlider {
        id: outputSlider
        visible: !panel.advanced
        node: panel.sink
        thin: true
        symbol: audio && audio.muted ? "speaker.slash.fill" : "speaker.fill"
        trailingSymbol: "speaker.wave.3.fill"
        handle: Rectangle {
            x: outputSlider.leftPadding + outputSlider.visualPosition * (outputSlider.availableWidth - width)
            y: outputSlider.topPadding + outputSlider.availableHeight / 2 - height / 2
            implicitWidth: 20
            implicitHeight: 16
            radius: 8
            color: "#ffffff"
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: Theme.menuSeparator
    }

    SectionLabel {
        visible: !panel.advanced
        text: "Output"
        Layout.topMargin: 2
    }

    Flickable {
        id: outputList
        visible: !panel.advanced
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(320, contentHeight)
        contentHeight: outputs.implicitHeight
        contentWidth: width
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        ScrollBar.vertical: ScrollBar {}

        WheelHandler {
            target: null
            onWheel: event => {
                const limit = Math.max(0, outputList.contentHeight - outputList.height);
                outputList.contentY = Math.max(0, Math.min(limit, outputList.contentY - event.angleDelta.y / 120 * 32));
            }
        }

        ColumnLayout {
            id: outputs
            width: outputList.width
            spacing: 0

            Repeater {
                model: panel.sinks

                DeviceRow {
                    selected: panel.sink === modelData
                    onPicked: Pipewire.preferredDefaultAudioSink = modelData
                }
            }

            Text {
                visible: panel.sinks.length === 0
                Layout.fillWidth: true
                text: "No Output Devices"
                color: Theme.menuSecondaryText
                font { family: Theme.fontFamily; pixelSize: 12 }
            }
        }
    }

    Flickable {
        id: advancedList
        visible: panel.advanced
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(400, contentHeight)
        contentHeight: advancedContent.implicitHeight
        contentWidth: width
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        ScrollBar.vertical: ScrollBar {}

        WheelHandler {
            target: null
            onWheel: event => {
                const limit = Math.max(0, advancedList.contentHeight - advancedList.height);
                advancedList.contentY = Math.max(0, Math.min(limit, advancedList.contentY - event.angleDelta.y / 120 * 32));
            }
        }

        ColumnLayout {
            id: advancedContent
            width: advancedList.width
            spacing: 6

            SectionLabel { text: "Input" }

            NodeSlider {
                node: panel.source
                input: true
            }

            Repeater {
                model: panel.sources

                DeviceRow {
                    selected: panel.source === modelData
                    onPicked: Pipewire.preferredDefaultAudioSource = modelData
                }
            }

            SectionLabel {
                visible: panel.streams.length > 0
                text: "Applications"
            }

            Repeater {
                model: panel.streams

                ColumnLayout {
                    id: app

                    required property var modelData
                    readonly property string iconName: (modelData.properties || {})["application.icon-name"] || ""

                    Layout.fillWidth: true
                    spacing: 4

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.leftMargin: 4
                        spacing: 6

                        IconImage {
                            visible: app.iconName !== ""
                            implicitSize: 14
                            source: app.iconName !== "" ? Quickshell.iconPath(app.iconName, true) : ""
                        }

                        Text {
                            Layout.fillWidth: true
                            text: panel.appLabel(app.modelData)
                            color: Theme.text
                            elide: Text.ElideRight
                            font { family: Theme.fontFamily; pixelSize: 12 }
                        }
                    }

                    NodeSlider { node: app.modelData }
                }
            }
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: Theme.menuSeparator
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 26
        radius: 6
        color: footerMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.08) : "transparent"

        Text {
            anchors { left: parent.left; verticalCenter: parent.verticalCenter }
            text: panel.advanced ? "Back to Output" : "Sound Settings..."
            color: Theme.menuText
            font { family: Theme.fontFamily; pixelSize: 13 }
        }

        MouseArea {
            id: footerMouse
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: panel.advanced = !panel.advanced
        }
    }
}
