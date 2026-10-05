import QtQuick
import QtQuick.Layouts
import Quickshell
import "../../theme"
import "../../widgets"

// macOS 27 Wi-Fi menu: power switch, the connected ("Known") network, and an
// expandable "Other Networks" list. Shared by the Wi-Fi menu extra and
// Control Center. Rows follow the measured 1x menu metrics in Theme.
ColumnLayout {
    id: panel

    required property var controls
    readonly property var state: controls.wifi
    readonly property bool busy: controls.actionTarget === "wifi" && controls.action.running
    readonly property var connectedNetwork: state.connected
        ? Object.assign({ "connected": true }, state.connected, (state.networks || []).find(n => n.connected) || {})
        : null
    readonly property var otherNetworks: (state.networks || []).filter(n => !n.connected)
    property string selectedSsid: ""
    property bool othersExpanded: false

    function reset() {
        password.text = "";
        selectedSsid = "";
        othersExpanded = false;
    }

    spacing: 0

    component Separator: Item {
        Layout.fillWidth: true
        implicitHeight: Theme.menuSeparatorHeight
        Rectangle {
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter
                leftMargin: Theme.menuTextInset - Theme.menuPadding; rightMargin: Theme.menuTextInset - Theme.menuPadding }
            height: 1
            color: Theme.menuSeparator
        }
    }

    component SectionLabel: Text {
        Layout.fillWidth: true
        Layout.leftMargin: Theme.menuTextInset - Theme.menuPadding
        Layout.preferredHeight: 22
        verticalAlignment: Text.AlignVCenter
        color: Theme.menuSecondaryText
        font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize - 1; weight: Font.DemiBold }
    }

    // Rounded hover row, 5px in from the glass edge like macOS status menus.
    component MenuRow: Rectangle {
        id: row
        property bool interactive: true
        signal clicked
        Layout.fillWidth: true
        radius: Theme.menuHighlightRadius
        color: interactive && rowMouse.containsMouse ? Qt.rgba(1, 1, 1, 0.12) : "transparent"
        MouseArea {
            id: rowMouse
            anchors.fill: parent
            hoverEnabled: true
            enabled: row.interactive
            onClicked: row.clicked()
        }
    }

    component NetworkRow: MenuRow {
        id: netRow
        required property var network
        implicitHeight: 34
        onClicked: {
            if (network.connected)
                panel.controls.wifiDisconnect();
            else if (!network.security)
                panel.controls.wifiConnect(network.ssid, "");
            else {
                panel.selectedSsid = network.ssid;
                password.forceActiveFocus();
            }
        }

        RowLayout {
            anchors { fill: parent; leftMargin: Theme.menuTextInset - Theme.menuPadding; rightMargin: Theme.menuTextInset - Theme.menuPadding }
            spacing: 8

            Rectangle {
                implicitWidth: 26
                implicitHeight: 26
                radius: 13
                color: netRow.network.connected ? Theme.menuHighlight : Qt.rgba(1, 1, 1, 0.16)

                WifiGlyph {
                    anchors.centerIn: parent
                    anchors.verticalCenterOffset: 1
                    level: netRow.network.signal >= 60 ? 3 : netRow.network.signal >= 30 ? 2 : 1
                    color: "white"
                    size: 13
                }
            }

            Text {
                Layout.fillWidth: true
                text: netRow.network.ssid
                color: Theme.menuText
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize }
            }

            SFSymbol {
                visible: !!netRow.network.security
                symbol: "lock.fill"
                size: 12
                color: Theme.menuSecondaryText
            }
        }
    }

    // Header: title and switch.
    RowLayout {
        Layout.fillWidth: true
        Layout.preferredHeight: 34
        Layout.leftMargin: Theme.menuTextInset - Theme.menuPadding
        Layout.rightMargin: Theme.menuTextInset - Theme.menuPadding

        Text {
            Layout.fillWidth: true
            text: "Wi-Fi"
            color: Theme.menuText
            font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize; weight: Font.DemiBold }
        }

        MacToggle {
            checked: panel.state.enabled
            enabled: !panel.controls.action.running
            onToggled: value => panel.controls.wifiPower(value)
        }
    }

    Separator { visible: panel.state.enabled }

    SectionLabel {
        visible: panel.state.enabled && !!panel.state.connected
        text: "Known Network"
    }

    NetworkRow {
        visible: panel.state.enabled && !!panel.state.connected
        network: panel.connectedNetwork || ({ "ssid": "", "signal": 0, "connected": true })
    }

    Separator { visible: panel.state.enabled && !!panel.state.connected }

    MenuRow {
        visible: panel.state.enabled
        implicitHeight: 26
        onClicked: {
            panel.othersExpanded = !panel.othersExpanded;
            if (panel.othersExpanded)
                panel.controls.wifiScan();
        }

        Text {
            anchors { left: parent.left; leftMargin: Theme.menuTextInset - Theme.menuPadding; verticalCenter: parent.verticalCenter }
            text: panel.busy ? "Other Networks…" : "Other Networks"
            color: Theme.menuSecondaryText
            font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize - 1; weight: Font.DemiBold }
        }

        SFSymbol {
            anchors { right: parent.right; rightMargin: Theme.menuTextInset - Theme.menuPadding; verticalCenter: parent.verticalCenter }
            symbol: "chevron.right"
            size: 11
            color: Theme.menuSecondaryText
            rotation: panel.othersExpanded ? 90 : 0
            Behavior on rotation { NumberAnimation { duration: 140 } }
        }
    }

    ListView {
        id: networks
        Layout.fillWidth: true
        Layout.preferredHeight: Math.min(contentHeight, 34 * 8)
        visible: panel.state.enabled && panel.othersExpanded
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: panel.otherNetworks
        delegate: NetworkRow {
            required property var modelData
            width: networks.width
            network: modelData
        }
    }

    // Password prompt for the selected secured network.
    RowLayout {
        Layout.fillWidth: true
        Layout.topMargin: 4
        Layout.bottomMargin: 4
        Layout.leftMargin: Theme.menuTextInset - Theme.menuPadding
        Layout.rightMargin: Theme.menuTextInset - Theme.menuPadding
        visible: panel.selectedSsid !== ""
        spacing: 6

        ThemedTextField {
            id: password
            Layout.fillWidth: true
            placeholderText: "Password for " + panel.selectedSsid
            echoMode: TextInput.Password
            onAccepted: {
                panel.controls.wifiConnect(panel.selectedSsid, password.text);
                password.text = "";
                panel.selectedSsid = "";
            }
            Keys.onEscapePressed: {
                password.text = "";
                panel.selectedSsid = "";
            }
        }
    }

    Text {
        id: errorText
        Layout.fillWidth: true
        Layout.leftMargin: Theme.menuTextInset - Theme.menuPadding
        Layout.rightMargin: Theme.menuTextInset - Theme.menuPadding
        Layout.topMargin: 2
        Layout.bottomMargin: 4
        visible: text !== ""
        text: panel.controls.actionTarget === "wifi" && panel.controls.actionError
            ? panel.controls.actionError : panel.state.error || ""
        color: Theme.danger
        wrapMode: Text.Wrap
        font { family: Theme.fontFamily; pixelSize: Theme.menuFontSize - 2 }
    }
}
