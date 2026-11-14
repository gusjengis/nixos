import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme"

Rectangle {
    id: card
    required property var session
    required property var overviewModel
    property bool selected: false
    property bool activeSession: false
    property bool previousSession: false
    property bool interactive: true
    property bool previewsEnabled: false
    property var tint: null
    readonly property bool tintHovered: !selected && mouse.containsMouse
    readonly property var overview: overviewModel.overview(session)
    readonly property var apps: overviewModel.apps(overview.windows)
    property string previewKey: ""
    onPreviewsEnabledChanged: previewKey = ""
    onSessionChanged: previewKey = ""
    readonly property var workspace: overview.groups.find(group => group.name + ":" + group.monitorId === previewKey) || overview.groups[0] || null
    signal activated()

    radius: 14
    color: tint && tint.composited ? (selected ? "#307abaff" : "transparent")
        : selected ? Qt.tint(tint ? tint.card : Theme.cardSurface, "#307abaff")
        : mouse.containsMouse ? (tint ? tint.hover : Theme.cardSurfaceHover)
        : (tint ? tint.card : Theme.cardSurface)
    border { width: selected ? 2 : 1; color: selected ? Theme.menuHighlight : "#22ffffff" }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 9
        spacing: 7

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 60
            Loader {
                objectName: "session-card-preview"
                readonly property real aspect: card.workspace ? card.workspace.width / card.workspace.height : 16 / 9
                anchors.centerIn: parent
                width: Math.min(parent.width, parent.height * aspect)
                height: width / aspect
                active: card.previewsEnabled
                sourceComponent: SessionPreview {
                    workspace: card.workspace
                    specialBlurRadius: card.overviewModel.specialBlurRadius === undefined ? 12 : card.overviewModel.specialBlurRadius
                    specialDim: card.overviewModel.specialDim || 0
                    iconForWindow: window => {
                        const key = window.initialClass || window.class || "";
                        const app = card.apps.find(app => app.key === key || (key.startsWith("context-terminal-") && app.key === "kitty"));
                        return app ? app.icon : "";
                    }
                }
            }
            Rectangle {
                anchors { top: parent.top; right: parent.right; margins: 5 }
                visible: status.text !== ""
                width: status.implicitWidth + 14; height: 21; radius: 10
                color: "#cc242426"
                Text {
                    id: status
                    anchors.centerIn: parent
                    text: card.session.closing ? "Closing…" : card.activeSession ? "Active" : card.previousSession ? "Previous" : ""
                    color: card.activeSession ? "#a9e5b3" : "#e6ffffff"
                    font { family: Theme.fontFamily; pixelSize: 10; weight: Font.Medium }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: card.session.name.split("/").pop()
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: "#f2ffffff"
                font { family: Theme.fontFamily; pixelSize: 14; weight: Font.DemiBold }
            }
            Text {
                text: (card.session.window_count || 0) + (card.session.window_count === 1 ? " window" : " windows")
                color: "#99ffffff"
                font { family: Theme.fontFamily; pixelSize: 10 }
            }
        }
        Text {
            Layout.fillWidth: true
            text: card.session.name.includes("/") ? card.session.name.substring(0, card.session.name.lastIndexOf("/")) : "Desktop session"
            textFormat: Text.PlainText
            elide: Text.ElideLeft
            color: "#80ffffff"
            font { family: Theme.fontFamily; pixelSize: 11 }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 4
            Repeater {
                model: card.apps.slice(0, 6)
                Image {
                    required property var modelData
                    Layout.preferredWidth: 22; Layout.preferredHeight: 22
                    source: modelData.icon
                    sourceSize: Qt.size(44, 44)
                }
            }
            Text {
                visible: card.apps.length > 6
                text: "+" + (card.apps.length - 6)
                color: "#99ffffff"
                font { family: Theme.fontFamily; pixelSize: 10 }
            }
            Item { Layout.fillWidth: true }
            Text {
                text: card.overview.groups.length + (card.overview.groups.length === 1 ? " view" : " views")
                color: "#80ffffff"
                font { family: Theme.fontFamily; pixelSize: 10 }
            }
        }
        Text {
            Layout.fillWidth: true
            rightPadding: Math.min(10, card.overview.groups.length) * 16
            text: card.workspace ? card.workspace.label + (card.workspace.monitor ? " · " + card.workspace.monitor : "") : "Empty session"
            elide: Text.ElideRight
            color: "#99ffffff"
            font { family: Theme.fontFamily; pixelSize: 10 }
        }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: card.interactive
        onClicked: card.activated()
    }
    // Hovering an occupied-view dot previews that workspace without switching.
    Row {
        anchors { right: parent.right; bottom: parent.bottom; margins: 10 }
        spacing: 4
        Repeater {
            model: card.overview.groups.slice(0, 10)
            Rectangle {
                id: dot
                required property var modelData
                width: 12; height: 12; radius: 6
                color: card.workspace && card.workspace.name === modelData.name && card.workspace.monitorId === modelData.monitorId ? "#e6ffffff" : "#55ffffff"
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: card.interactive
                    onEntered: card.previewKey = dot.modelData.name + ":" + dot.modelData.monitorId
                    onClicked: card.previewKey = dot.modelData.name + ":" + dot.modelData.monitorId
                }
            }
        }
    }
}
