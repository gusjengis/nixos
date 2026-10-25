import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "state"
import "theme"

Scope {
    id: root

    readonly property string contextId: DesktopSessions.contextCatalog.active_context || ""
    readonly property var contextNode: (DesktopSessions.contextCatalog.nodes || []).find(node => node.id === contextId) || ({})
    readonly property string contextName: contextNode.breadcrumb || DesktopSessions.activeName
    readonly property int sectionCount: Number(notebook.cards.some(card => card.status === "In-Progress"))
        + Number(notebook.cards.some(card => card.status === "Todo"))

    ListModel { id: cardModel }
    Connections {
        target: notebook
        function onCardsChanged() {
            cardModel.clear();
            for (const card of notebook.cards)
                cardModel.append(card);
        }
    }

    PersistentProperties {
        id: preferences
        reloadableId: "context-work-widget"
        property bool shown: true
    }

    IpcHandler {
        target: "contextWork"
        function toggle(): void { preferences.shown = !preferences.shown; }
    }

    InProgressModel {
        id: notebook
        contextId: root.contextId
    }

    Variants {
        model: Quickshell.screens

        delegate: PanelWindow {
            id: window
            required property var modelData
            screen: modelData
            visible: preferences.shown && root.contextId !== ""
            color: "transparent"
            exclusionMode: ExclusionMode.Ignore
            focusable: false
            anchors { top: true; right: true }
            margins { top: Theme.barHeight + 12; right: 8 }
            implicitWidth: 360
            implicitHeight: Math.min(560, Math.max(160, screen.height - Theme.barHeight - 64),
                136 + Math.max(1, notebook.cards.length) * 64 + 28 * root.sectionCount)
            WlrLayershell.layer: WlrLayer.Bottom
            WlrLayershell.namespace: "quickshell-in-progress"
            // Only the rounded card receives input; shadow margins pass through.
            mask: Region { item: panel; radius: panel.radius }

            Rectangle {
                id: panel
                anchors.fill: parent
                anchors.margins: 20
                radius: 24
                color: "#cf252932"
                border.width: 1
                border.color: "#30ffffff"
                gradient: Gradient {
                    GradientStop { position: 0; color: "#dc363a43" }
                    GradientStop { position: 1; color: "#d121252d" }
                }
                layer.enabled: true
                layer.effect: MultiEffect {
                    shadowEnabled: true
                    shadowColor: "#60000000"
                    shadowBlur: 0.7
                    shadowVerticalOffset: 5
                }

                Column {
                    id: header
                    anchors { top: parent.top; left: parent.left; right: parent.right; margins: 20 }
                    spacing: 5

                    Row {
                        width: parent.width
                        Text {
                            width: parent.width - count.width
                            text: "Your Work"
                            textFormat: Text.PlainText
                            color: "#79b7ff"
                            font { family: Theme.fontFamily; pixelSize: 21; weight: Font.Bold; letterSpacing: -0.5 }
                        }
                        Text {
                            id: count
                            text: notebook.loaded && !notebook.error ? notebook.cards.length : "–"
                            color: "#79b7ff"
                            font { family: Theme.fontFamily; pixelSize: 24; weight: Font.Bold; letterSpacing: -0.8 }
                        }
                    }

                    Text {
                        width: parent.width
                        text: root.contextName
                        textFormat: Text.PlainText
                        elide: Text.ElideLeft
                        color: "#99ffffff"
                        font { family: Theme.fontFamily; pixelSize: 12; weight: Font.Medium }
                    }
                }

                ListView {
                    id: list
                    objectName: "context-work-list"
                    anchors { top: header.bottom; topMargin: 14; bottom: parent.bottom; bottomMargin: 12; left: parent.left; right: parent.right; leftMargin: 10; rightMargin: 10 }
                    clip: true
                    model: cardModel
                    section.property: "status"
                    section.criteria: ViewSection.FullString
                    section.delegate: Text {
                        required property string section
                        width: list.width
                        height: 28
                        leftPadding: 10
                        topPadding: 4
                        text: section === "In-Progress" ? "IN PROGRESS" : "TO DO"
                        color: section === "In-Progress" ? "#79b7ff" : "#99ffffff"
                        font { family: Theme.fontFamily; pixelSize: 10; weight: Font.Bold; letterSpacing: 0.7 }
                    }
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 4 }

                    delegate: Rectangle {
                        id: row
                        required property string title
                        required property string path
                        required property string status
                        required property int index
                        width: list.width
                        height: Math.max(56, cardTitle.implicitHeight + 24)
                        radius: 10
                        color: mouse.pressed ? "#20ffffff" : mouse.containsMouse ? "#10ffffff" : "transparent"

                        // Reminders-style ring is a status indicator, not a checkbox.
                        Rectangle {
                            x: 10; y: 17
                            width: 17; height: 17; radius: 9
                            color: "transparent"
                            border { width: 1.5; color: "#77ffffff" }
                            Rectangle { anchors.centerIn: parent; width: 5; height: 5; radius: 3; color: "#79b7ff"; visible: row.status === "In-Progress" }
                        }

                        Text {
                            id: cardTitle
                            anchors { left: parent.left; leftMargin: 38; right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                            text: row.title
                            textFormat: Text.PlainText
                            color: "#f2ffffff"
                            wrapMode: Text.Wrap
                            maximumLineCount: 2
                            elide: Text.ElideRight
                            font { family: Theme.fontFamily; pixelSize: 14; weight: Font.Medium; letterSpacing: -0.15 }
                        }

                        Rectangle {
                            anchors { bottom: parent.bottom; left: parent.left; leftMargin: 38; right: parent.right; rightMargin: 10 }
                            height: 1
                            color: "#18ffffff"
                            visible: row.index < notebook.cards.length - 1
                        }

                        MouseArea {
                            id: mouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: notebook.openCard(row.path)
                        }
                    }
                }

                Text {
                    anchors { fill: list; leftMargin: 10; rightMargin: 10 }
                    visible: notebook.cards.length === 0
                    text: notebook.error ? "Notebook unavailable" : notebook.loaded ? "No work queued" : "Loading your notes…"
                    textFormat: Text.PlainText
                    color: "#99ffffff"
                    verticalAlignment: Text.AlignVCenter
                    wrapMode: Text.Wrap
                    font { family: Theme.fontFamily; pixelSize: 14 }
                }
            }
        }
    }
}
