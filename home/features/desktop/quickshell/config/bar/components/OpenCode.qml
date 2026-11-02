import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import "../../theme"

Rectangle {
    id: root
    required property var service
    readonly property bool popupVisible: popup.visible
    implicitWidth: 32
    implicitHeight: Theme.barItemHeight
    radius: height / 2
    color: popup.visible || mouse.containsMouse ? Theme.barHoverFill : "transparent"
    Accessible.role: Accessible.Button
    Accessible.name: "OpenCode sessions, " + service.attentionCount + " need attention"
    Accessible.onPressAction: popup.toggle(root)

    IpcHandler {
        target: "opencodeMenu-" + (root.QsWindow.window ? root.QsWindow.window.screen.name : "unknown")
        function toggle(): void { popup.toggle(root); }
        function close(): void { popup.visible = false; }
        function isOpen(): bool { return popup.visible; }
        function timings(): string {
            return JSON.stringify({firstPaintMs: popup.firstPaintMs, prepared: popup.contentReady,
                border: popup.borderSize, radius: popup.popupRadius});
        }
    }

    Image {
        anchors.centerIn: parent
        width: 15
        height: 15
        source: "icons/opencode.svg"
        sourceSize: Qt.size(72, 90)
        fillMode: Image.PreserveAspectFit
        mipmap: true
        layer.enabled: true
        layer.effect: MultiEffect {
            colorization: 1
            colorizationColor: Theme.barText
        }
    }
    Rectangle {
        x: 24; y: 1
        width: 6; height: 6; radius: 3
        visible: root.service.attentionCount > 0
        color: root.service.attentionColor
        border { width: 0.5; color: "#66000000" }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: popup.toggle(root)
    }
    OpenCodePopup { id: popup; service: root.service }
}
