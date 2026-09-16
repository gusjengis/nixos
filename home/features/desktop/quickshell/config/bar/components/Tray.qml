import QtQuick
import QtQuick.Layouts
import Quickshell.Services.SystemTray
import Quickshell.Widgets
import "../../theme"

RowLayout {
    id: root

    spacing: 4

    TrayMenu { id: contextMenu }

    Repeater {
        model: SystemTray.items

        delegate: Rectangle {
            required property var modelData
            implicitWidth: 28
            implicitHeight: 28
            radius: Theme.radius
            color: mouse.containsMouse ? Theme.surfaceHover : "transparent"

            IconImage {
                anchors.centerIn: parent
                implicitSize: 18
                source: parent.modelData.icon
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
