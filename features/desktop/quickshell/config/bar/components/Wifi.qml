import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import "../../theme"
import "../../widgets"

Rectangle {
    id: root

    required property var controls
    readonly property var state: controls.wifi
    readonly property bool busy: controls.actionTarget === "wifi" && controls.action.running

    implicitWidth: 28
    implicitHeight: 28
    radius: Theme.radius
    color: mouse.containsMouse || popup.visible ? Theme.surfaceHover : "transparent"

    function alpha(source, amount) {
        return Qt.rgba(source.r, source.g, source.b, amount);
    }

    WifiIcon {
        anchors.centerIn: parent
        signal: root.state.connected ? root.state.connected.signal : 0
        enabled: root.state.enabled
        connected: !!root.state.connected
        iconColor: root.state.enabled ? Theme.text : Theme.muted
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: popup.toggle(root)
    }

    GuardedPopupWindow {
        id: popup
        property string selectedSsid: ""

        function toggle(anchorItem) {
            if (visible) {
                visible = false;
                return;
            }
            anchor.item = anchorItem;
            visible = true;
            selectedSsid = "";
            root.controls.refreshWifi();
        }

        anchor.rect.x: root.width - width
        anchor.rect.y: Theme.barPopupY(anchor.item)
        implicitWidth: 380
        implicitHeight: Math.min(480, content.implicitHeight + 32)
        color: "transparent"

        Rectangle {
            anchors.fill: parent
            radius: Theme.windowRadius
            color: Theme.background
            border { width: Theme.windowBorderWidth; color: Theme.windowBorder }
        }

        ColumnLayout {
            id: content
            anchors { fill: parent; margins: 16 }
            spacing: 10

            // Header
            RowLayout {
                Layout.fillWidth: true
                spacing: 10

                Rectangle {
                    implicitWidth: 34
                    implicitHeight: 34
                    radius: Theme.radius
                    color: root.state.enabled ? root.alpha(Theme.accentStrong, 0.18) : Theme.surface
                    border { width: 1; color: root.state.enabled ? root.alpha(Theme.accentStrong, 0.5) : "transparent" }

                    WifiIcon {
                        anchors.centerIn: parent
                        signal: root.state.connected ? root.state.connected.signal : 0
                        enabled: root.state.enabled
                        connected: !!root.state.connected
                        iconColor: root.state.enabled ? Theme.accent : Theme.muted
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
                        text: !root.state.enabled ? "Disabled"
                            : root.state.connected ? "Connected to " + root.state.connected.ssid
                            : "Not connected"
                        color: root.state.connected ? Theme.accent : Theme.muted
                        elide: Text.ElideRight
                        font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2 }
                    }
                }

                ThemedToggle {
                    checked: root.state.enabled
                    enabled: !root.controls.action.running
                    onToggled: value => root.controls.wifiPower(value)
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 1
                color: root.alpha(Theme.border, 0.5)
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
                    visible: root.state.enabled
                    text: (root.state.networks || []).length + " found"
                    color: Theme.muted
                    font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 3 }
                }

                ThemedButton {
                    variant: "ghost"
                    iconText: "󰑐"
                    text: root.busy ? "Scanning" : "Scan"
                    implicitWidth: 96
                    enabled: root.state.enabled && !root.controls.action.running
                    onClicked: root.controls.wifiScan()
                }
            }

            // Error banner
            Rectangle {
                Layout.fillWidth: true
                visible: errorText.text !== ""
                implicitHeight: errorText.implicitHeight + 16
                radius: Theme.radius
                color: root.alpha(Theme.danger, 0.14)
                border { width: 1; color: root.alpha(Theme.danger, 0.45) }

                Text {
                    id: errorText
                    anchors { fill: parent; margins: 8 }
                    text: root.controls.actionTarget === "wifi" && root.controls.actionError
                        ? root.controls.actionError : root.state.error || ""
                    color: Theme.danger
                    wrapMode: Text.Wrap
                    verticalAlignment: Text.AlignVCenter
                    font { family: Theme.fontFamily; pixelSize: Theme.fontSize - 2 }
                }
            }

            // Password prompt
            Rectangle {
                Layout.fillWidth: true
                visible: popup.selectedSsid !== ""
                implicitHeight: prompt.implicitHeight + 20
                radius: Theme.radius + 2
                color: root.alpha(Theme.accentStrong, 0.1)
                border { width: 1; color: root.alpha(Theme.accentStrong, 0.45) }

                ColumnLayout {
                    id: prompt
                    anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
                        leftMargin: 10; rightMargin: 10 }
                    spacing: 6

                    Text {
                        Layout.fillWidth: true
                        text: "󰌾  " + popup.selectedSsid
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
                                popup.selectedSsid = "";
                            }
                        }

                        ThemedButton {
                            id: connectButton
                            variant: "accent"
                            text: "Connect"
                            implicitWidth: 84
                            implicitHeight: 32
                            enabled: !root.controls.action.running
                            onClicked: {
                                root.controls.wifiConnect(popup.selectedSsid, password.text);
                                password.text = "";
                                popup.selectedSsid = "";
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
                                popup.selectedSsid = "";
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
                visible: !root.state.enabled || (root.state.networks || []).length === 0
                text: root.state.enabled ? "No networks found" : "Wi-Fi is turned off"
                color: Theme.muted
                font { family: Theme.fontFamily; pixelSize: Theme.fontSize }
            }

            ListView {
                id: networks
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(contentHeight, 330)
                visible: root.state.enabled && (root.state.networks || []).length > 0
                clip: true
                spacing: 4
                boundsBehavior: Flickable.StopAtBounds
                model: root.state.networks || []
                ScrollBar.vertical: ThemedScrollBar { }

                delegate: Rectangle {
                    id: networkRow
                    required property var modelData
                    width: networks.width - (networks.contentHeight > networks.height ? 10 : 0)
                    height: 50
                    radius: Theme.radius + 2
                    color: modelData.connected ? root.alpha(Theme.accentStrong, 0.16)
                        : networkMouse.containsMouse ? Theme.surfaceHover
                        : popup.selectedSsid === modelData.ssid ? Theme.surfaceHover : Theme.surface
                    border {
                        width: 1
                        color: modelData.connected ? root.alpha(Theme.accentStrong, 0.55)
                            : popup.selectedSsid === networkRow.modelData.ssid ? root.alpha(Theme.accent, 0.45)
                            : root.alpha(Theme.border, 0.45)
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
                                root.controls.wifiDisconnect();
                            else if (!networkRow.modelData.security)
                                root.controls.wifiConnect(networkRow.modelData.ssid, "");
                            else {
                                popup.selectedSsid = networkRow.modelData.ssid;
                                password.forceActiveFocus();
                            }
                        }
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
