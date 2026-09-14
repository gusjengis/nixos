import QtQuick
import QtQuick.Layouts
import Quickshell.Hyprland
import "../../theme"

RowLayout {
    id: root

    required property var barScreen
    readonly property var monitor: Hyprland.monitorFor(barScreen)
    spacing: 4

    function workspaceName(number) {
        return root.monitor ? root.monitor.name + ":" + number : "";
    }

    function occupied(number) {
        return Hyprland.workspaces.values.some(workspace =>
            (workspace.name === root.workspaceName(number) || workspace.id === number)
                && workspace.monitor === root.monitor);
    }

    Repeater {
        model: 10

        delegate: Rectangle {
            required property int index
            readonly property int number: index + 1
            readonly property bool active: root.monitor && root.monitor.activeWorkspace
                && (root.monitor.activeWorkspace.name === root.workspaceName(number)
                    || root.monitor.activeWorkspace.id === number)
            readonly property bool occupied: root.occupied(number)

            implicitWidth: number === 10 ? 28 : 24
            implicitHeight: 26
            radius: Theme.radius
            color: active ? Theme.accentStrong
                : mouse.containsMouse ? Theme.surfaceHover
                : occupied ? Theme.surface : "transparent"
            border.color: occupied && !active ? Theme.border : "transparent"

            Text {
                anchors.centerIn: parent
                text: parent.number
                color: parent.active ? Theme.background
                    : parent.occupied ? Theme.text : Theme.muted
                font { family: Theme.fontFamily; pixelSize: Theme.fontSize; bold: parent.active }
            }

            MouseArea {
                id: mouse
                anchors.fill: parent
                hoverEnabled: true
                onClicked: {
                    if (root.monitor)
                        Hyprland.dispatch("hl.dsp.focus({ monitor = '" + root.monitor.name + "' })");
                    Hyprland.dispatch("hl.dsp.focus({ workspace = 'name:"
                        + root.workspaceName(parent.number) + "'"
                        + ", on_current_monitor = true })");
                }
            }
        }
    }
}
