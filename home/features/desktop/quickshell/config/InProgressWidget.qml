import QtQuick
import QtQuick.Controls
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
            readonly property int shadowPadding: Theme.glassShadowPadding
            readonly property int bodyHeight: Math.min(Math.max(120, screen.height - Theme.barHeight - 104),
                62 + Math.max(1, notebook.cards.length) * 64 + 28 * root.sectionCount
                    + (root.sectionCount > 1 ? 12 : 0))
            screen: modelData
            visible: preferences.shown && root.contextId !== ""
            color: "transparent"
            exclusionMode: ExclusionMode.Ignore
            focusable: false
            anchors { bottom: true; left: true }
            margins { bottom: 28 - window.shadowPadding; left: 28 - window.shadowPadding }
            implicitWidth: 320 + 2 * shadowPadding
            // Grow to fit active work instead of stopping after roughly seven
            // rows. Oversized boards scroll, initially showing In-Progress.
            implicitHeight: bodyHeight + 2 * shadowPadding
            // Render after workspace blur, like a fixed, pinned window.
            WlrLayershell.layer: WlrLayer.Top
            WlrLayershell.namespace: "quickshell-in-progress"
            // Only the rounded card receives input; shadow margins pass through.
            mask: Region { item: panel; radius: panel.radius }

            Rectangle {
                id: panel
                anchors.fill: parent
                anchors.margins: window.shadowPadding
                radius: 24
                color: Theme.glassActive ? "transparent" : Theme.background
                border.width: Theme.glassActive ? 0 : 1
                border.color: "#30ffffff"

                Column {
                    id: header
                    anchors { top: parent.top; left: parent.left; right: parent.right; margins: 20 }
                    spacing: 5

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
                    onCountChanged: Qt.callLater(() => list.positionViewAtEnd())
                    onHeightChanged: Qt.callLater(() => list.positionViewAtEnd())
                    section.property: "status"
                    section.criteria: ViewSection.FullString
                    section.delegate: Text {
                        required property string section
                        readonly property int sectionGap: section === "In-Progress" && root.sectionCount > 1 ? 12 : 0
                        width: list.width
                        height: 28 + sectionGap
                        leftPadding: 10
                        topPadding: 4 + sectionGap
                        text: section === "In-Progress" ? "IN PROGRESS" : "TO DO"
                        color: "#ffffff"
                        font { family: Theme.fontFamily; pixelSize: 10; weight: Font.DemiBold; letterSpacing: 0.7 }
                    }
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 4 }

                    delegate: Rectangle {
                        id: row
                        required property string title
                        required property string path
                        required property string status
                        required property int index
                        readonly property string contextLabel: model.owner_context_id && model.owner_context_id !== root.contextId ? (model.context || "") : ""
                        width: list.width
                        height: 64
                        radius: 10
                        color: mouse.pressed ? "#20ffffff" : mouse.containsMouse ? "#10ffffff" : "transparent"

                        // Reminders-style ring is a status indicator, not a checkbox.
                        Rectangle {
                            x: 10
                            anchors.verticalCenter: parent.verticalCenter
                            width: 17; height: 17; radius: 9
                            color: "transparent"
                            border { width: 1.5; color: "#77ffffff" }
                            Rectangle { anchors.centerIn: parent; width: 5; height: 5; radius: 3; color: "#ffffff"; visible: row.status === "In-Progress" }
                        }

                        Column {
                            anchors { left: parent.left; leftMargin: 38; right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                            spacing: 3
                            Text {
                                id: cardTitle
                                width: parent.width
                                text: row.title
                                textFormat: Text.PlainText
                                color: "#f2ffffff"
                                wrapMode: Text.Wrap
                                maximumLineCount: 2
                                elide: Text.ElideRight
                                font { family: Theme.fontFamily; pixelSize: 14; weight: Font.Medium; letterSpacing: -0.15 }
                            }
                            Text {
                                width: parent.width
                                visible: row.contextLabel !== ""
                                text: row.contextLabel
                                textFormat: Text.PlainText
                                color: "#99ffffff"
                                elide: Text.ElideLeft
                                font { family: Theme.fontFamily; pixelSize: 10 }
                            }
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
