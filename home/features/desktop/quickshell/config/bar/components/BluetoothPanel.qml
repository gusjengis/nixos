import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../widgets"

// Bluetooth power and device list, shown as a Control Center detail page.
ColumnLayout {
    id: panel

    required property var controls
    readonly property var state: controls.bluetooth
    readonly property var deviceList: state.devices || []
    readonly property bool connected: deviceList.some(device => device.connected)
    readonly property bool busy: controls.actionTarget === "bluetooth" && controls.action.running

    function alpha(source, amount) {
        return Qt.rgba(source.r, source.g, source.b, amount);
    }

    function deviceIcon(device) {
        const name = (device.name || "").toLowerCase();
        if (name.includes("headphone") || name.includes("headset") || name.includes("buds")
                || name.includes("airpod"))
            return "󰋋";
        if (name.includes("speaker") || name.includes("soundbar") || name.includes("audio"))
            return "󰓃";
        if (name.includes("mouse"))
            return "󰍽";
        if (name.includes("keyboard"))
            return "󰌌";
        if (name.includes("controller") || name.includes("gamepad") || name.includes("xbox")
                || name.includes("dualsense"))
            return "󰊴";
        if (name.includes("phone") || name.includes("pixel") || name.includes("galaxy")
                || name.includes("iphone"))
            return "󰄜";
        if (name.includes("watch") || name.includes("band"))
            return "󰖉";
        return "󰂯";
    }

    spacing: 10

    // Header
    RowLayout {
        Layout.fillWidth: true
        spacing: 10

        Rectangle {
            implicitWidth: 34
            implicitHeight: 34
            radius: Theme.radius
            color: panel.state.powered ? panel.alpha(Theme.accentStrong, 0.18) : Theme.surface
            border { width: 1; color: panel.state.powered ? panel.alpha(Theme.accentStrong, 0.5) : "transparent" }

            Text {
                anchors.centerIn: parent
                text: panel.state.powered ? (panel.connected ? "󰂱" : "󰂯") : "󰂲"
                color: panel.state.powered ? Theme.accent : Theme.muted
                font { family: Theme.iconFontFamily; pixelSize: 18 }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 1

            Text {
                Layout.fillWidth: true
                text: "Bluetooth"
                color: Theme.text
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: 15; bold: true }
            }

            Text {
                Layout.fillWidth: true
                text: !panel.state.powered ? "Disabled"
                    : panel.connected ? "Connected"
                    : "No device connected"
                color: panel.connected ? Theme.accent : Theme.muted
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2 }
            }
        }

        ThemedToggle {
            checked: panel.state.powered
            enabled: !panel.controls.action.running
            onToggled: value => panel.controls.bluetoothPower(value)
        }
    }

    Rectangle {
        Layout.fillWidth: true
        implicitHeight: 1
        color: panel.alpha(Theme.border, 0.5)
    }

    // Section bar
    RowLayout {
        Layout.fillWidth: true
        spacing: 8

        Text {
            Layout.fillWidth: true
            text: "Devices"
            color: Theme.muted
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3; bold: true }
        }

        Text {
            visible: panel.state.powered
            text: panel.deviceList.length + " found"
            color: Theme.muted
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3 }
        }

        ThemedButton {
            variant: "ghost"
            iconText: "󰑐"
            text: panel.busy ? "Scanning" : "Scan"
            implicitWidth: 96
            enabled: panel.state.powered && !panel.controls.action.running
            onClicked: panel.controls.bluetoothScan()
        }
    }

    // Error banner
    Rectangle {
        Layout.fillWidth: true
        visible: errorText.text !== ""
        implicitHeight: errorText.implicitHeight + 16
        radius: Theme.radius
        color: panel.alpha(Theme.danger, 0.14)
        border { width: 1; color: panel.alpha(Theme.danger, 0.45) }

        Text {
            id: errorText
            anchors { fill: parent; margins: 8 }
            text: panel.controls.actionTarget === "bluetooth" && panel.controls.actionError
                ? panel.controls.actionError : panel.state.error || ""
            color: Theme.danger
            wrapMode: Text.Wrap
            verticalAlignment: Text.AlignVCenter
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2 }
        }
    }

    Text {
        Layout.fillWidth: true
        Layout.preferredHeight: visible ? 64 : 0
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        visible: !panel.state.powered || panel.deviceList.length === 0
        text: panel.state.powered ? "No devices found" : "Bluetooth is turned off"
        color: Theme.muted
        font { family: Theme.fontFamily; pixelSize: Theme.fontSize }
    }

    ListView {
        id: devices
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(contentHeight, 330)
        visible: panel.state.powered && panel.deviceList.length > 0
        clip: true
        spacing: 5
        boundsBehavior: Flickable.StopAtBounds
        model: panel.deviceList
        ScrollBar.vertical: ThemedScrollBar { }

        delegate: Rectangle {
            id: deviceRow
            required property var modelData
            width: devices.width - (devices.contentHeight > devices.height ? 10 : 0)
            height: 58
            radius: Theme.radius + 2
            color: modelData.connected ? panel.alpha(Theme.accentStrong, 0.16)
                : deviceMouse.containsMouse ? Theme.surfaceHover : Theme.surface
            border {
                width: 1
                color: modelData.connected ? panel.alpha(Theme.accentStrong, 0.55)
                    : panel.alpha(Theme.border, 0.45)
            }

            Behavior on color { ColorAnimation { duration: 110 } }

            MouseArea {
                id: deviceMouse
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }

            RowLayout {
                anchors { fill: parent; leftMargin: 11; rightMargin: 10 }
                spacing: 10

                Text {
                    text: panel.deviceIcon(deviceRow.modelData)
                    color: deviceRow.modelData.connected ? Theme.accent : Theme.text
                    font { family: Theme.iconFontFamily; pixelSize: 18 }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1

                    Text {
                        Layout.fillWidth: true
                        text: deviceRow.modelData.name || deviceRow.modelData.address
                        color: Theme.text
                        elide: Text.ElideRight
                        font {
                            family: Theme.fontFamily
                            pixelSize: Theme.fontSize
                            bold: deviceRow.modelData.connected
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: deviceRow.modelData.connected ? "Connected"
                            : deviceRow.modelData.paired ? "Paired" : deviceRow.modelData.address
                        color: deviceRow.modelData.connected ? Theme.accent : Theme.muted
                        elide: Text.ElideRight
                        font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3 }
                    }
                }

                ThemedButton {
                    variant: deviceRow.modelData.connected ? "normal" : "accent"
                    text: deviceRow.modelData.connected ? "Disconnect"
                        : deviceRow.modelData.paired ? "Connect" : "Pair"
                    implicitWidth: 92
                    enabled: panel.state.powered && !panel.controls.action.running
                    onClicked: panel.controls.bluetoothAction(
                        deviceRow.modelData.connected ? "disconnect"
                            : deviceRow.modelData.paired ? "connect" : "pair",
                        deviceRow.modelData.address)
                }

                ThemedButton {
                    variant: "danger"
                    iconText: "󰩹"
                    visible: deviceRow.modelData.paired
                    implicitWidth: 34
                    leftPadding: 8
                    rightPadding: 8
                    enabled: panel.state.powered && !panel.controls.action.running
                    onClicked: panel.controls.bluetoothAction("remove", deviceRow.modelData.address)
                }
            }
        }
    }
}
