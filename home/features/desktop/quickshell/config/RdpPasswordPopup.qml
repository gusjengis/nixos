import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "theme"

ShellRoot {
    id: root
    property string errorMessage: Quickshell.env("RDP_POPUP_ERROR")
    property bool busy: false
    property bool sessionActive: false

    function submit() {
        if (busy || !password.text.length || !worker.running)
            return;
        errorMessage = "";
        busy = true;
        worker.write(JSON.stringify({password: password.text}) + "\n");
    }

    Process {
        id: worker
        command: [Quickshell.env("RDP_POPUP_PYTHON"), Quickshell.env("RDP_POPUP_SCRIPT"),
                  Quickshell.env("RDP_POPUP_CSV"), Quickshell.env("RDP_POPUP_OPTIONS"),
                  "--popup-worker", Quickshell.env("RDP_POPUP_NAME")]
        stdinEnabled: true
        running: true
        stdout: SplitParser {
            onRead: data => {
                let result;
                try { result = JSON.parse(data); } catch (_) { return; }
                if (result.error) {
                    root.sessionActive = false;
                    root.busy = false;
                    root.errorMessage = result.error;
                    password.forceActiveFocus();
                    password.selectAll();
                } else if (result.connected) {
                    password.clear();
                    root.sessionActive = true;
                } else if (result.finished) {
                    Qt.quit();
                }
            }
        }
        onExited: (code, status) => {
            if (root.sessionActive && code === 0) {
                Qt.quit();
            } else {
                root.busy = false;
                root.sessionActive = false;
                root.errorMessage = "Connection helper stopped. Close this dialog and try again.";
            }
        }
    }

    PanelWindow {
        id: popup
        visible: !root.sessionActive
        color: "transparent"
        implicitWidth: 440 + 2 * Theme.glassShadowPadding
        implicitHeight: body.height + 2 * Theme.glassShadowPadding
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.namespace: "quickshell-panel"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: visible ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        mask: Region { item: body }

        Rectangle {
            id: body
            x: Theme.glassShadowPadding
            y: Theme.glassShadowPadding
            width: 440
            height: content.implicitHeight + 48
            radius: Theme.panelRadius
            color: Theme.glassActive ? "transparent" : Theme.backgroundBase
            border.width: Theme.glassActive ? 0 : 1
            border.color: Theme.windowBorder

            ColumnLayout {
                id: content
                anchors.fill: parent
                anchors.margins: 24
                spacing: 12

                Label {
                    text: Quickshell.env("RDP_POPUP_NAME")
                    textFormat: Text.PlainText
                    color: "white"
                    font.family: Theme.fontFamily
                    font.pixelSize: 24
                    font.weight: Font.DemiBold
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                }
                TextField {
                    id: password
                    Layout.fillWidth: true
                    Layout.preferredHeight: 44
                    focus: true
                    enabled: !root.busy
                    echoMode: TextInput.Password
                    inputMethodHints: Qt.ImhHiddenText | Qt.ImhSensitiveData | Qt.ImhNoPredictiveText
                    placeholderText: "Password"
                    color: "white"
                    placeholderTextColor: Qt.rgba(1, 1, 1, 0.55)
                    selectionColor: Qt.rgba(1, 1, 1, 0.25)
                    selectedTextColor: "white"
                    font.family: Theme.fontFamily
                    font.pixelSize: 17
                    leftPadding: 12
                    rightPadding: 12
                    background: Rectangle {
                        radius: 10
                        color: Qt.rgba(0, 0, 0, 0.16)
                        border.width: 1
                        border.color: Qt.rgba(1, 1, 1, password.activeFocus ? 0.55 : 0.2)
                    }
                    onAccepted: root.submit()
                    Keys.onEscapePressed: Qt.quit()
                }
                Label {
                    Layout.fillWidth: true
                    visible: root.busy || root.errorMessage.length > 0
                    text: root.busy ? "Connecting…" : root.errorMessage
                    textFormat: Text.PlainText
                    color: root.busy ? Qt.rgba(1, 1, 1, 0.7) : "#ff7474"
                    font.family: Theme.fontFamily
                    font.pixelSize: 14
                    wrapMode: Text.Wrap
                }
                RowLayout {
                    Layout.alignment: Qt.AlignRight
                    spacing: 10
                    Button {
                        text: "Cancel"
                        onClicked: Qt.quit()
                        contentItem: Text {
                            text: parent.text
                            color: "white"
                            font.family: Theme.fontFamily
                            font.pixelSize: 14
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            implicitWidth: 86
                            implicitHeight: 36
                            radius: 9
                            color: Qt.rgba(1, 1, 1, 0.12)
                        }
                    }
                    Button {
                        text: root.errorMessage ? "Try again" : "Connect"
                        enabled: !root.busy && password.text.length > 0 && worker.running
                        onClicked: root.submit()
                        contentItem: Text {
                            text: parent.text
                            color: "white"
                            opacity: parent.enabled ? 1 : 0.5
                            font.family: Theme.fontFamily
                            font.pixelSize: 14
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                        background: Rectangle {
                            implicitWidth: 102
                            implicitHeight: 36
                            radius: 9
                            color: "#007aff"
                            opacity: parent.enabled ? 1 : 0.45
                        }
                    }
                }
            }
            Keys.onEscapePressed: Qt.quit()
        }
    }
}
