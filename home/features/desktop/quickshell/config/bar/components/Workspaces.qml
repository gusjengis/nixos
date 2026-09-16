import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import Quickshell.Hyprland
import "../../theme"

RowLayout {
    id: root

    required property var barScreen
    readonly property var monitor: Hyprland.monitorFor(barScreen)
    readonly property var specialWorkspaces: [
        { "name": "terminal", "glyph": "\uf120" },
        { "name": "browser", "glyph": "\uf268" },
        { "name": "calendar", "glyph": "\uf073" },
        { "name": "gpt", "logo": "icons/chatgpt.svg" },
        { "name": "gis", "glyph": "\uf279" },
        { "name": "db", "glyph": "\uf1c0" },
        { "name": "slack", "logo": "icons/slack.svg" },
        { "name": "discord", "logo": "icons/discord.svg" },
        { "name": "notes", "logo": "icons/obsidian.svg" },
        { "name": "music", "logo": "icons/qobuz.svg" },
        { "name": "musicassistant", "glyph": "\uf001" },
        { "name": "email", "glyph": "\uf0e0" },
        { "name": "home", "logo": "icons/home-assistant.svg" }
    ]
    readonly property var occupiedSpecialWorkspaces: specialWorkspaces.filter(entry => {
        const workspace = root.specialWorkspace(entry.name);
        return workspace && workspace.monitor === root.monitor
            && workspace.toplevels.values.length > 0;
    })
    spacing: 4

    function workspaceName(number) {
        return root.monitor ? root.monitor.name + ":" + number : "";
    }

    function occupied(number) {
        return Hyprland.workspaces.values.some(workspace =>
            (workspace.name === root.workspaceName(number) || workspace.id === number)
                && workspace.monitor === root.monitor);
    }

    function specialWorkspace(name) {
        return Hyprland.workspaces.values.find(workspace =>
            workspace.name === "special:" + name);
    }

    function specialWorkspaceActive(name) {
        const special = root.monitor && root.monitor.lastIpcObject
            ? root.monitor.lastIpcObject.specialWorkspace : null;
        return special && special.name === "special:" + name;
    }

    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (event.name === "activespecial")
                Hyprland.refreshMonitors();
        }
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

    RowLayout {
        visible: root.occupiedSpecialWorkspaces.length > 0
        Layout.leftMargin: 4
        spacing: 4

        Repeater {
            model: root.occupiedSpecialWorkspaces

            delegate: Rectangle {
                required property var modelData
                readonly property var workspace: root.specialWorkspace(modelData.name)
                readonly property bool active: root.specialWorkspaceActive(modelData.name)

                implicitWidth: 28
                implicitHeight: 26
                radius: Theme.radius
                color: active ? Theme.accentStrong
                    : specialMouse.containsMouse ? Theme.surfaceHover : Theme.surface
                border.color: !active ? Theme.border : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: typeof parent.modelData.glyph === "string"
                        ? parent.modelData.glyph : ""
                    visible: text !== ""
                    color: parent.active ? Theme.background : Theme.text
                    font { family: Theme.iconFontFamily; pixelSize: 16 }
                }

                Image {
                    id: brandIcon
                    anchors.centerIn: parent
                    width: 17
                    height: 17
                    visible: source.toString() !== ""
                    source: typeof parent.modelData.logo === "string"
                        ? parent.modelData.logo : ""
                    cache: false
                    fillMode: Image.PreserveAspectFit
                    layer.enabled: true
                    layer.effect: MultiEffect {
                        colorization: 1
                        colorizationColor: brandIcon.parent.active
                            ? Theme.background : Theme.text
                    }
                }

                MouseArea {
                    id: specialMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: Hyprland.dispatch("hl.dsp.workspace.toggle_special('"
                        + parent.modelData.name + "')")
                }
            }
        }
    }
}
