import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../theme"
import "../../widgets"

// Wi-Fi network list, shared by the Wi-Fi menu extra and Control Center.
ColumnLayout {
    id: panel

    required property var controls
    readonly property var state: controls.wifi
    readonly property bool busy: controls.actionTarget === "wifi" && controls.action.running
    property string selectedSsid: ""

    function alpha(source, amount) {
        return Qt.rgba(source.r, source.g, source.b, amount);
    }

    function reset() {
        password.text = "";
        selectedSsid = "";
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
            color: panel.state.enabled ? panel.alpha(Theme.accentStrong, 0.18) : Theme.surface
            border { width: 1; color: panel.state.enabled ? panel.alpha(Theme.accentStrong, 0.5) : "transparent" }

            WifiIcon {
                anchors.centerIn: parent
                signal: panel.state.connected ? panel.state.connected.signal : 0
                enabled: panel.state.enabled
                connected: !!panel.state.connected
                iconColor: panel.state.enabled ? Theme.accent : Theme.muted
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 1

            Text {
                Layout.fillWidth: true
                text: "Wi-Fi"
                color: Theme.text
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: 15; bold: true }
            }

            Text {
                Layout.fillWidth: true
                text: !panel.state.enabled ? "Disabled"
                    : panel.state.connected ? "Connected to " + panel.state.connected.ssid
                    : "Not connected"
                color: panel.state.connected ? Theme.accent : Theme.muted
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2 }
            }
        }

        ThemedToggle {
            checked: panel.state.enabled
            enabled: !panel.controls.action.running
            onToggled: value => panel.controls.wifiPower(value)
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
            text: "Networks"
            color: Theme.muted
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3; bold: true }
        }

        Text {
            visible: panel.state.enabled
            text: (panel.state.networks || []).length + " found"
            color: Theme.muted
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3 }
        }

        ThemedButton {
            variant: "ghost"
            iconText: "󰑐"
            text: panel.busy ? "Scanning" : "Scan"
            implicitWidth: 96
            enabled: panel.state.enabled && !panel.controls.action.running
            onClicked: panel.controls.wifiScan()
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
            text: panel.controls.actionTarget === "wifi" && panel.controls.actionError
                ? panel.controls.actionError : panel.state.error || ""
            color: Theme.danger
            wrapMode: Text.Wrap
            verticalAlignment: Text.AlignVCenter
            font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2 }
        }
    }

    // Password prompt
    Rectangle {
        Layout.fillWidth: true
        visible: panel.selectedSsid !== ""
        implicitHeight: prompt.implicitHeight + 20
        radius: Theme.radius + 2
        color: panel.alpha(Theme.accentStrong, 0.1)
        border { width: 1; color: panel.alpha(Theme.accentStrong, 0.45) }

        ColumnLayout {
            id: prompt
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
                leftMargin: 10; rightMargin: 10 }
            spacing: 6

            Text {
                Layout.fillWidth: true
                text: "󰌾  " + panel.selectedSsid
                color: Theme.text
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 1; bold: true }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 6

                ThemedTextField {
                    id: password
                    Layout.fillWidth: true
                    placeholderText: "Password (blank uses saved profile)"
                    echoMode: TextInput.Password
                    onAccepted: connectButton.clicked()
                    Keys.onEscapePressed: {
                        password.text = "";
                        panel.selectedSsid = "";
                    }
                }

                ThemedButton {
                    id: connectButton
                    variant: "accent"
                    text: "Connect"
                    implicitWidth: 84
                    implicitHeight: 32
                    enabled: !panel.controls.action.running
                    onClicked: {
                        panel.controls.wifiConnect(panel.selectedSsid, password.text);
                        password.text = "";
                        panel.selectedSsid = "";
                    }
                }

                ThemedButton {
                    variant: "ghost"
                    iconText: "󰅖"
                    implicitWidth: 32
                    implicitHeight: 32
                    leftPadding: 8
                    rightPadding: 8
                    onClicked: {
                        password.text = "";
                        panel.selectedSsid = "";
                    }
                }
            }
        }
    }

    Text {
        Layout.fillWidth: true
        Layout.preferredHeight: visible ? 64 : 0
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        visible: !panel.state.enabled || (panel.state.networks || []).length === 0
        text: panel.state.enabled ? "No networks found" : "Wi-Fi is turned off"
        color: Theme.muted
        font { family: Theme.fontFamily; pixelSize: Theme.fontSize }
    }

    ListView {
        id: networks
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(contentHeight, 330)
        visible: panel.state.enabled && (panel.state.networks || []).length > 0
        clip: true
        spacing: 4
        boundsBehavior: Flickable.StopAtBounds
        model: panel.state.networks || []
        ScrollBar.vertical: ThemedScrollBar { }

        delegate: Rectangle {
            id: networkRow
            required property var modelData
            width: networks.width - (networks.contentHeight > networks.height ? 10 : 0)
            height: 50
            radius: Theme.radius + 2
            color: modelData.connected ? panel.alpha(Theme.accentStrong, 0.16)
                : networkMouse.containsMouse ? Theme.surfaceHover
                : panel.selectedSsid === modelData.ssid ? Theme.surfaceHover : Theme.surface
            border {
                width: 1
                color: modelData.connected ? panel.alpha(Theme.accentStrong, 0.55)
                    : panel.selectedSsid === networkRow.modelData.ssid ? panel.alpha(Theme.accent, 0.45)
                    : panel.alpha(Theme.border, 0.45)
            }

            Behavior on color { ColorAnimation { duration: 110 } }

            RowLayout {
                anchors { fill: parent; leftMargin: 11; rightMargin: 11 }
                spacing: 10

                WifiIcon {
                    signal: networkRow.modelData.signal
                    iconColor: networkRow.modelData.connected ? Theme.accent : Theme.text
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1

                    Text {
                        Layout.fillWidth: true
                        text: networkRow.modelData.ssid
                        color: Theme.text
                        elide: Text.ElideRight
                        font {
                            family: Theme.fontFamily
                            pixelSize: Theme.fontSize
                            bold: networkRow.modelData.connected
                        }
                    }

                    Text {
                        Layout.fillWidth: true
                        text: networkRow.modelData.connected ? "Connected"
                            : networkRow.modelData.security || "Open"
                        color: networkRow.modelData.connected ? Theme.accent : Theme.muted
                        elide: Text.ElideRight
                        font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3 }
                    }
                }

                Text {
                    visible: !!networkRow.modelData.security
                    text: "󰌾"
                    color: Theme.muted
                    font { family: Theme.iconFontFamily; pixelSize: 13 }
                }

                Text {
                    Layout.minimumWidth: 32
                    horizontalAlignment: Text.AlignRight
                    text: networkRow.modelData.signal + "%"
                    color: Theme.muted
                    font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2 }
                }
            }

            MouseArea {
                id: networkMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (networkRow.modelData.connected)
                        panel.controls.wifiDisconnect();
                    else if (!networkRow.modelData.security)
                        panel.controls.wifiConnect(networkRow.modelData.ssid, "");
                    else {
                        panel.selectedSsid = networkRow.modelData.ssid;
                        password.forceActiveFocus();
                    }
                }
            }
        }
    }
}
