import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.SystemTray
import Quickshell.Widgets
import "../../theme"

RowLayout {
    id: root

    readonly property bool popupVisible: contextMenu.visible
    // Compiled by Nix from shaders/tray-mono.frag (qsb output is not
    // hand-editable), then linked into the data dir by default.nix.
    readonly property url monoShader: "file://" + (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share")
        + "/quickshell/shaders/tray-mono.frag.qsb"
    spacing: 4

    TrayMenu { id: contextMenu }

    Repeater {
        model: SystemTray.items

        delegate: Rectangle {
            required property var modelData
            implicitWidth: 28
            implicitHeight: 28
            radius: Theme.radius
            color: hover.hovered ? Theme.barHoverFill : "transparent"

            // App-supplied icons can be any color, so they are recolored to
            // follow the bar's black/white content; see shaders/tray-mono.frag.
            IconImage {
                anchors.centerIn: parent
                implicitSize: 20
                source: parent.modelData.icon
                layer.enabled: true
                layer.smooth: true
                layer.effect: ShaderEffect {
                    property real darkContent: Theme.barContentIsDark ? 1 : 0
                    fragmentShader: root.monoShader
                }
            }

            HoverHandler {
                id: hover
                blocking: false
            }

            MouseArea {
                id: mouse
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
                onClicked: event => {
                    if (event.button === Qt.MiddleButton)
                        parent.modelData.secondaryActivate();
                    else if (event.button === Qt.RightButton || parent.modelData.onlyMenu)
                        contextMenu.show(parent.modelData, parent);
                    else
                        parent.modelData.activate();
                }
                onWheel: event => parent.modelData.scroll(event.angleDelta.y, false)
            }
        }
    }
}
