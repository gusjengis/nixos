import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.Pipewire
import Quickshell.Widgets
import "../../theme"
import "../../widgets"

// Control Center's expanded Sound module, doubling as a small pavucontrol:
// default output/input levels, every hardware device (click to make it the
// default), and a level per playing application.
ColumnLayout {
    id: panel

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
        onMoved: audio.volume = value
        onSymbolClicked: audio.muted = !audio.muted

        Binding {
            target: slider
            property: "value"
            value: slider.audio ? slider.audio.volume : 0
            when: !slider.pressed
        }
    }

    component SectionLabel: Text {
        Layout.fillWidth: true
        Layout.topMargin: 8
        color: Theme.muted
        font { family: Theme.fontFamily; pixelSize: 12; weight: Font.DemiBold }
    }

    // macOS device row: round glyph badge, filled with the accent when the
    // device is the current default.
    component DeviceRow: Rectangle {
        id: row

        required property var modelData
        property bool selected
        signal picked()

        Layout.fillWidth: true
        implicitHeight: 34
        radius: 8
        color: rowMouse.containsMouse ? Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, 0.08) : "transparent"

        RowLayout {
            anchors { fill: parent; leftMargin: 4; rightMargin: 8 }
            spacing: 9

            Rectangle {
                implicitWidth: 26
                implicitHeight: 26
                radius: 13
                color: row.selected ? Theme.accentStrong : Qt.rgba(Theme.text.r, Theme.text.g, Theme.text.b, 0.16)

                SFSymbol {
                    anchors.centerIn: parent
                    symbol: panel.deviceSymbol(row.modelData)
                    size: 12
                    color: row.selected ? "#ffffff" : Theme.text
                }
            }

            Text {
                Layout.fillWidth: true
                text: panel.label(row.modelData)
                color: Theme.text
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
        text: "Sound"
        color: Theme.text
        font { family: Theme.fontFamily; pixelSize: 13; weight: Font.DemiBold }
    }

    NodeSlider { node: panel.sink }

    SectionLabel { text: "Output" }

    Repeater {
        model: panel.sinks

        DeviceRow {
            selected: panel.sink === modelData
            onPicked: Pipewire.preferredDefaultAudioSink = modelData
        }
    }

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
