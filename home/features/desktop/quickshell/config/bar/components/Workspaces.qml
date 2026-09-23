import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import Quickshell.Hyprland
import Quickshell.Io
import "../../theme"

RowLayout {
    id: root

    required property var barScreen
    readonly property var monitor: Hyprland.monitorFor(barScreen)
    property var workspaceState: []
    property bool refreshPending: false
    readonly property var specialWorkspaces: [
        {
            "name": "terminal",
            "glyph": "\uf120"
        },
        {
            "name": "browser",
            "glyph": "\uf268"
        },
        {
            "name": "calendar",
            "glyph": "\uf073"
        },
        {
            "name": "gpt",
            "logo": "icons/chatgpt.svg"
        },
        {
            "name": "gis",
            "glyph": "\uf279"
        },
        {
            "name": "db",
            "glyph": "\uf1c0"
        },
        {
            "name": "slack",
            "logo": "icons/slack.svg"
        },
        {
            "name": "discord",
            "logo": "icons/discord.svg"
        },
        {
            "name": "notes",
            "logo": "icons/obsidian.svg"
        },
        {
            "name": "music",
            "logo": "icons/qobuz.svg"
        },
        {
            "name": "musicassistant",
            "glyph": "\uf025"
        },
        {
            "name": "email",
            "glyph": "\uf0e0"
        },
        {
            "name": "home",
            "logo": "icons/home-assistant.svg"
        }
    ]
    readonly property var occupiedSpecialWorkspaces: specialWorkspaces.filter(entry => {
        const workspace = root.specialWorkspace(entry.name);
        return workspace && root.monitor && workspace.monitor === root.monitor.name && workspace.windows > 0;
    })
    spacing: 4

    function workspaceName(number) {
        return root.monitor ? root.monitor.name + ":" + number : "";
    }

    function occupied(number) {
        return workspaceState.some(workspace => (workspace.name === root.workspaceName(number) || workspace.id === number) && root.monitor && workspace.monitor === root.monitor.name);
    }

    function specialWorkspace(name) {
        return workspaceState.find(workspace => workspace.name === "special:" + name);
    }

    function specialWorkspaceActive(name) {
        const special = root.monitor && root.monitor.lastIpcObject ? root.monitor.lastIpcObject.specialWorkspace : null;
        return special && special.name === "special:" + name;
    }

    function refreshState() {
        Hyprland.refreshMonitors();
        if (workspaceRequest.running)
            refreshPending = true;
        else
            workspaceRequest.running = true;
    }

    Process {
        id: workspaceRequest
        command: ["hyprctl", "-j", "workspaces"]
        stdout: StdioCollector { id: workspaceOutput }

        onExited: (code, status) => {
            if (code === 0 && status === 0) {
                try {
                    root.workspaceState = JSON.parse(workspaceOutput.text);
                } catch (error) {
                    console.warn("Cannot parse Hyprland workspaces:", error);
                }
            }
            if (root.refreshPending) {
                root.refreshPending = false;
                workspaceRequest.running = true;
            }
        }
    }

    Component.onCompleted: refreshState()

    Connections {
        target: Hyprland
        function onRawEvent(event) {
            const relevant = ["workspace", "workspacev2", "createworkspace", "createworkspacev2", "destroyworkspace", "destroyworkspacev2", "moveworkspace", "moveworkspacev2", "openwindow", "closewindow", "movewindow", "movewindowv2", "activespecial"];
            if (relevant.indexOf(event.name) !== -1)
                root.refreshState();
        }
    }

    Repeater {
        model: 10

        delegate: Rectangle {
            required property int index
            readonly property int number: index + 1
            readonly property var activeWorkspace: root.monitor && root.monitor.lastIpcObject ? root.monitor.lastIpcObject.activeWorkspace : null
            readonly property bool active: activeWorkspace && (activeWorkspace.name === root.workspaceName(number) || activeWorkspace.id === number)
            readonly property bool occupied: root.occupied(number)

            implicitWidth: number === 10 ? 28 : 24
            implicitHeight: 26
            radius: Theme.radius
            color: active ? Theme.accentStrong : mouse.containsMouse ? Theme.surfaceHover : occupied ? Theme.surface : "transparent"
            border.color: occupied && !active ? Theme.border : "transparent"

            Text {
                anchors.centerIn: parent
                // text: ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"][parent.index]
                text: parent.number
                // Occupied/hovered numbers sit on their own Theme.surface(Hover)
                // chip, unaffected by the wallpaper. An idle, unoccupied number
                // has no chip at all though - it floats directly on the
                // wallpaper - so it needs the reactive bar color instead.
                color: parent.active ? Theme.background : parent.occupied ? Theme.text : (mouse.containsMouse ? Theme.muted : Theme.barMuted)
                font {
                    family: Theme.fontFamily
                    pixelSize: Theme.fontSize
                    weight: Font.DemiBold
                }
            }

            MouseArea {
                id: mouse
                anchors.fill: parent
                hoverEnabled: true
                onClicked: {
                    if (root.monitor)
                        Hyprland.dispatch("hl.dsp.focus({ monitor = '" + root.monitor.name + "' })");
                    Hyprland.dispatch("hl.dsp.focus({ workspace = 'name:" + root.workspaceName(parent.number) + "'" + ", on_current_monitor = true })");
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
                color: active ? Theme.accentStrong : specialMouse.containsMouse ? Theme.surfaceHover : Theme.surface
                border.color: !active ? Theme.border : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: typeof parent.modelData.glyph === "string" ? parent.modelData.glyph : ""
                    visible: text !== ""
                    color: parent.active ? Theme.background : Theme.text
                    font {
                        family: Theme.iconFontFamily
                        pixelSize: 16
                    }
                }

                Image {
                    id: brandIcon
                    anchors.centerIn: parent
                    width: 17
                    height: 17
                    visible: source.toString() !== ""
                    source: typeof parent.modelData.logo === "string" ? parent.modelData.logo : ""
                    cache: false
                    fillMode: Image.PreserveAspectFit
                    layer.enabled: true
                    layer.effect: MultiEffect {
                        colorization: 1
                        colorizationColor: brandIcon.parent.active ? Theme.background : Theme.text
                    }
                }

                MouseArea {
                    id: specialMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: Hyprland.dispatch("hl.dsp.workspace.toggle_special('" + parent.modelData.name + "')")
                }
            }
        }
    }
}
