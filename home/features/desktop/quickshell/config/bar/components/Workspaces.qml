import QtQuick
import QtQuick.Effects
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import "../../theme"
import "../../state"

RowLayout {
    id: root

    required property var barScreen
    readonly property var monitor: Hyprland.monitorFor(barScreen)
    property var workspaceState: []
    property bool refreshPending: false
    readonly property var specialWorkspaces: [
        {
            "name": "terminal",
            "glyph": "\uf489",
            // Octicon draws its frame well inside the em box.
            "glyphSize": 20
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
        return root.monitor ? DesktopSessions.workspaceName(number, root.monitor.name) : "";
    }

    function occupied(number) {
        return workspaceState.some(workspace => (workspace.address || workspace.name) === root.workspaceName(number) && root.monitor && workspace.monitor === root.monitor.name && workspace.windows > 0);
    }

    function specialWorkspace(name) {
        return workspaceState.find(workspace => (workspace.address || workspace.name) === DesktopSessions.specialName(name));
    }

    function specialWorkspaceActive(name) {
        const special = root.monitor && root.monitor.lastIpcObject ? root.monitor.lastIpcObject.specialWorkspace : null;
        return !!special && (special.address || special.name) === DesktopSessions.specialName(name);
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
        target: DesktopSessions
        function onSnapshotChanged() { root.refreshState(); }
    }

    Rectangle {
        implicitWidth: Math.min(110, sessionLabel.implicitWidth + 16)
        implicitHeight: 26
        radius: Theme.radius
        color: sessionMouse.containsMouse ? Theme.barHoverFill : "transparent"
        Text {
            id: sessionLabel
            anchors.fill: parent
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            verticalAlignment: Text.AlignVCenter
            text: DesktopSessions.activeName
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: DesktopSessions.error ? Theme.danger : Theme.barText
            font { family: Theme.fontFamily; pixelSize: 13; weight: Font.DemiBold }
        }
        MouseArea {
            id: sessionMouse
            anchors.fill: parent
            hoverEnabled: true
            onClicked: Quickshell.execDetached(["qs", "ipc", "call", "sessions", "toggle"])
        }
    }

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
            readonly property bool active: !!activeWorkspace && (activeWorkspace.address || activeWorkspace.name) === root.workspaceName(number)
            readonly property bool occupied: root.occupied(number)

            visible: active || occupied
            implicitWidth: number === 10 ? 28 : 24
            implicitHeight: 26
            radius: Theme.radius
            // Monochrome, following the wallpaper: the active workspace is a
            // solid barText chip with an inverted number; everything else
            // floats on the wallpaper. Occupied numbers are full strength,
            // empty ones muted.
            color: active ? Theme.barText : mouse.containsMouse ? Theme.barHoverFill : "transparent"

            Text {
                anchors.centerIn: parent
                // text: ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"][parent.index]
                text: parent.number
                color: parent.active ? Theme.barTextInverse : parent.occupied ? Theme.barText : Theme.barContentIsDark ? Qt.rgba(0, 0, 0, 0.35) : Theme.barMuted
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
                        DesktopSessions.selectWorkspace(parent.number, root.monitor.name);
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
                // Chip only while the special workspace is shown.
                color: active ? Theme.barText : specialMouse.containsMouse ? Theme.barHoverFill : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: typeof parent.modelData.glyph === "string" ? parent.modelData.glyph : ""
                    visible: text !== ""
                    color: parent.active ? Theme.barTextInverse : Theme.barText
                    font {
                        family: Theme.iconFontFamily
                        pixelSize: parent.modelData.glyphSize || 16
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
                        colorizationColor: brandIcon.parent.active ? Theme.barTextInverse : Theme.barText
                    }
                }

                MouseArea {
                    id: specialMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: {
                        if (root.monitor)
                            DesktopSessions.toggleSpecial(parent.modelData.name, root.monitor.name);
                    }
                }
            }
        }
    }
}
