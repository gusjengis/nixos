import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import "state"
import "theme"
import "widgets"

PanelWindow {
    id: picker

    property string renameId: ""
    property var closeTarget: null
    property bool awaiting: false
    property bool dispensary: false
    readonly property var results: (dispensary ? DesktopSessions.savedContexts : DesktopSessions.openSessions).filter(session => session.name.toLowerCase().includes(search.text.trim().toLowerCase()))
    readonly property var selected: list.currentIndex >= 0 ? results[list.currentIndex] : null
    readonly property int shadowPadding: Theme.glassShadowPadding
    readonly property int bodyWidth: Math.min(900, screen.width - 32)
    readonly property int galleryColumns: bodyWidth - 32 >= 620 ? 2 : 1
    readonly property real galleryCellHeight: Math.max(235,
        ((bodyWidth - 32) / galleryColumns - 26) * screen.height / screen.width + 120)
    readonly property int bodyHeight: Math.min(780, screen.height * 0.78,
        180 + Math.min(2, Math.ceil(Math.max(1, results.length) / galleryColumns)) * galleryCellHeight)

    visible: false
    focusable: true
    exclusionMode: ExclusionMode.Ignore
    anchors.top: true
    margins.top: Math.max(0, Math.round(screen.height * 0.1) - shadowPadding)
    implicitWidth: bodyWidth + 2 * shadowPadding
    implicitHeight: bodyHeight + 2 * shadowPadding
    color: "transparent"
    WlrLayershell.namespace: "quickshell-session-picker"
    mask: Region { item: panel; radius: panel.radius }

    SessionOverviewModel { id: sessionOverview }

    WallpaperTint {
        id: sessionTint
        screen: picker.screen
        region: Qt.rect((picker.screen.width - picker.bodyWidth) / 2,
            picker.margins.top + picker.shadowPadding, picker.bodyWidth, picker.bodyHeight)
        enabled: picker.visible
        composited: neutralCards.active
    }

    NeutralSurfaces {
        id: neutralCards
        namespace: "quickshell-session-picker"
        enabled: picker.visible
        radius: Theme.panelRadius
        clip: ({ x: galleryLayout.x + list.x, y: galleryLayout.y + list.y, width: list.width, height: list.height })
        rectangles: {
            // Explicit dependencies: mapToItem alone does not observe scrolling
            // or delegate relayout through C++'s coordinate mapper.
            const scroll = list.contentY;
            const children = list.contentItem.children;
            return children.filter(card => card.tintHovered !== undefined && list.visible
                && card.y + card.height > scroll && card.y < scroll + list.height).map(card => ({
                    x: galleryLayout.x + list.x + card.x,
                    y: galleryLayout.y + list.y + card.y - scroll,
                    width: card.width, height: card.height, radius: card.radius, hovered: card.tintHovered
                }));
        }
    }

    // Initialize Quickshell's capture buffer manager before the popup's scene
    // graph starts. Dynamically loaded previews otherwise subscribe too late
    // for that one-time initialization signal and never receive a first frame.
    ScreencopyView { visible: false }

    function open(mode) {
        const changedMode = mode !== undefined && mode !== dispensary;
        if (mode !== undefined)
            dispensary = mode;
        closeTarget = null;
        if (!visible || changedMode) {
            const monitor = Hyprland.focusedMonitor;
            const focusedScreen = Quickshell.screens.find(candidate => monitor && candidate.name === monitor.name);
            if (focusedScreen)
                screen = focusedScreen;
            renameId = "";
            search.text = "";
            list.currentIndex = Math.max(0, results.findIndex(session => session.runtime_id === DesktopSessions.active));
            visible = true;
        }
        search.forceActiveFocus();
    }

    function toggle(mode) {
        if (DesktopSessions.busy)
            return;
        mode = mode === true;
        closeTarget = null;
        if (visible && dispensary === mode)
            visible = false;
        else
            open(mode);
    }

    function beginRename() {
        if (closeTarget || !selected || DesktopSessions.busy)
            return;
        renameId = selected.id;
        search.text = selected.persistent ? selected.name.split("/").pop() : selected.name;
        search.selectAll();
        search.forceActiveFocus();
    }

    function submit(create) {
        if (closeTarget || DesktopSessions.busy)
            return;
        if (renameId)
            awaiting = DesktopSessions.rename(renameId, search.text);
        else if (create || !selected) {
            if (dispensary && search.text.trim())
                awaiting = DesktopSessions.create(search.text);
        }
        else
            awaiting = DesktopSessions.switchSession(selected.id);
    }

    function beginClose() {
        if (dispensary || renameId || closeTarget || !selected || !selected.runtime_id || DesktopSessions.busy)
            return;
        closeTarget = { id: selected.runtime_id, name: selected.name, windowCount: selected.window_count };
        search.forceActiveFocus();
    }

    function confirmClose() {
        if (!closeTarget || DesktopSessions.busy)
            return;
        if (!DesktopSessions.sessions.some(session => session.id === closeTarget.id)) {
            closeTarget = null;
            DesktopSessions.error = "Session no longer exists. Select a session again.";
            return;
        }
        if (DesktopSessions.closeSession(closeTarget.id)) {
            closeTarget = null;
            awaiting = false;
        }
    }

    HyprlandFocusGrab {
        id: focusGrab
        windows: [picker]
        onCleared: {
            if (!FocusGuard.suspended && !DesktopSessions.busy && !DesktopSessions.error)
                picker.visible = false;
        }
    }

    Binding {
        target: focusGrab
        property: "active"
        value: picker.visible && !FocusGuard.suspended
    }

    Connections {
        target: DesktopSessions
        function onSessionsChanged() {
            if (picker.closeTarget && !DesktopSessions.sessions.some(session => session.id === picker.closeTarget.id)) {
                picker.closeTarget = null;
                if (!DesktopSessions.busy && !picker.awaiting)
                    DesktopSessions.error = "Session no longer exists. Select a session again.";
            }
        }
        function onCompleted(action) {
            if (!picker.awaiting)
                return;
            picker.awaiting = false;
            if (action === "rename") {
                picker.renameId = "";
                search.text = "";
            } else {
                if (action === "close") {
                    picker.closeTarget = null;
                    search.text = "";
                }
                picker.visible = false;
            }
        }
        function onFailed() {
            picker.awaiting = false;
            if (!picker.visible)
                picker.open();
            else
                search.forceActiveFocus();
        }
    }

    Rectangle {
        id: panel
        objectName: "session-picker-body"
        anchors.fill: parent
        anchors.margins: picker.shadowPadding
        radius: Theme.panelRadius
        color: Theme.glassActive ? "transparent" : sessionTint.surface
        border.color: "#30ffffff"
        border.width: Theme.glassActive ? 0 : 1

        ColumnLayout {
            id: galleryLayout
            anchors.fill: parent
            anchors.margins: 16
            spacing: 12

            RowLayout {
                Layout.fillWidth: true
                Layout.leftMargin: 8
                Layout.rightMargin: 8
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text {
                        text: picker.closeTarget ? "Close running session?" : picker.renameId ? "Rename session" : picker.dispensary ? "Session dispensary" : "Sessions"
                        color: Theme.menuText
                        font { family: Theme.fontFamily; pixelSize: 22; weight: Font.DemiBold }
                    }
                    Text {
                        text: picker.dispensary ? "Your saved contexts" : "Your open contexts, at a glance"
                        color: Theme.menuSecondaryText
                        font { family: Theme.fontFamily; pixelSize: 12 }
                    }
                }
                Rectangle {
                    implicitWidth: sessionCount.implicitWidth + 18
                    implicitHeight: 24
                    radius: 12
                    color: "#12ffffff"
                    Text {
                        id: sessionCount
                        anchors.centerIn: parent
                        text: picker.results.length + (picker.dispensary ? " saved" : " open")
                        color: "#b3ffffff"
                        font { family: Theme.fontFamily; pixelSize: 11; weight: Font.Medium }
                    }
                }
            }

            ThemedTextField {
                id: search
                Layout.fillWidth: true
                implicitHeight: 40
                color: Theme.menuText
                placeholderTextColor: Theme.menuSecondaryText
                selectionColor: Theme.menuHighlight
                selectedTextColor: "#ffffff"
                leftPadding: 36
                font.pixelSize: 14
                background: Rectangle {
                    radius: 10
                    color: "#18000000"
                    border.width: 1
                    border.color: search.activeFocus ? "#5599c9ff" : "#18ffffff"
                    Text {
                        x: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: "⌕"
                        color: Theme.menuSecondaryText
                        font { family: Theme.fontFamily; pixelSize: 24 }
                    }
                }
                placeholderText: picker.renameId ? "Session name" : picker.dispensary ? "Search or create, e.g. Computing/Desktop" : "Search open sessions"
                readOnly: DesktopSessions.busy || picker.closeTarget !== null
                onTextChanged: list.currentIndex = 0
                Keys.onPressed: event => {
                    const ctrl = (event.modifiers & Qt.ControlModifier) !== 0;
                    if (picker.closeTarget) {
                        event.accepted = true;
                        if (event.isAutoRepeat || DesktopSessions.busy)
                            return;
                        if (event.key === Qt.Key_Escape || (event.key === Qt.Key_N && event.modifiers === Qt.NoModifier))
                            picker.closeTarget = null;
                        else if (event.key === Qt.Key_Y && event.modifiers === Qt.NoModifier)
                            picker.confirmClose();
                        return;
                    }
                    if (ctrl && event.key === Qt.Key_D) {
                        if (!event.isAutoRepeat)
                            picker.beginClose();
                    } else if (event.key === Qt.Key_Escape) {
                        picker.visible = false;
                    } else if (event.key === Qt.Key_F2 || (ctrl && event.key === Qt.Key_R)) {
                        picker.beginRename();
                    } else if (ctrl && event.key === Qt.Key_N) {
                        if (picker.dispensary && !picker.renameId)
                            picker.submit(true);
                    } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                        picker.submit(false);
                    } else if (!picker.renameId && event.key === Qt.Key_Down) {
                        list.currentIndex = Math.min(picker.results.length - 1, list.currentIndex + list.columns);
                    } else if (!picker.renameId && event.key === Qt.Key_Up) {
                        list.currentIndex = Math.max(0, list.currentIndex - list.columns);
                    } else if (!picker.renameId && event.key === Qt.Key_Right && search.text === "") {
                        list.currentIndex = Math.min(picker.results.length - 1, list.currentIndex + 1);
                    } else if (!picker.renameId && event.key === Qt.Key_Left && search.text === "") {
                        list.currentIndex = Math.max(0, list.currentIndex - 1);
                    } else {
                        return;
                    }
                    event.accepted = true;
                }
            }

            Text {
                Layout.fillWidth: true
                visible: picker.closeTarget !== null
                text: picker.closeTarget ? "Close session \"" + picker.closeTarget.name + "\" (" + picker.closeTarget.windowCount + " windows)? Saved context and notes remain. Unsaved application work may be lost if an app doesn't prompt. Global scratchpads are untouched.\nY: close session   N / Esc: cancel" : ""
                textFormat: Text.PlainText
                color: Theme.danger
                wrapMode: Text.Wrap
                font { family: Theme.fontFamily; pixelSize: 13 }
            }

            Text {
                Layout.fillWidth: true
                visible: DesktopSessions.error !== ""
                text: DesktopSessions.error
                textFormat: Text.PlainText
                color: Theme.danger
                wrapMode: Text.Wrap
                maximumLineCount: 4
                elide: Text.ElideRight
                font { family: Theme.fontFamily; pixelSize: 13 }
            }

            Text {
                Layout.fillWidth: true
                visible: !picker.closeTarget || DesktopSessions.busy
                text: DesktopSessions.busy ? "Applying session change..." : !DesktopSessions.available ? "No live Hyprland session." : picker.renameId ? (picker.dispensary ? "Enter: save name (close running context first)   Esc: cancel" : "Enter: save runtime name   Esc: cancel") : !picker.dispensary && picker.selected && picker.selected.closing ? "Applications may still need confirmation. Enter: return; Ctrl+D: retry close." : picker.dispensary ? (picker.results.length === 0 && search.text.trim() ? "Enter: create saved session \"" + search.text.trim() + "\"" : "Enter: open or restore   Ctrl+N: create (Parent/Child for nesting)   F2: rename") : picker.results.length === 0 ? "No matching open sessions. Super+Shift+Z opens the dispensary." : "Enter: switch   F2: rename runtime session   Ctrl+D: close   Super+Shift+Z: dispensary"
                textFormat: Text.PlainText
                color: "#99ffffff"
                wrapMode: Text.Wrap
                font { family: Theme.fontFamily; pixelSize: 13 }
            }

            GridView {
                id: list
                objectName: "session-gallery"
                readonly property int columns: picker.galleryColumns
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: !picker.renameId
                clip: true
                cellWidth: width / columns
                cellHeight: picker.galleryCellHeight
                boundsBehavior: Flickable.StopAtBounds
                model: picker.results
                currentIndex: 0
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded; width: 4 }

                delegate: SessionCard {
                    tint: sessionTint
                    required property var modelData
                    required property int index
                    width: list.cellWidth - 8
                    height: list.cellHeight - 8
                    session: picker.results[index]
                    overviewModel: sessionOverview
                    selected: list.currentIndex === index
                    activeSession: modelData.runtime_id === DesktopSessions.active
                    previousSession: modelData.runtime_id === DesktopSessions.snapshot.previous
                    interactive: !picker.closeTarget && !DesktopSessions.busy
                    previewsEnabled: picker.visible && y + height > list.contentY && y < list.contentY + list.height
                    onActivated: {
                        list.currentIndex = index;
                        picker.submit(false);
                    }
                }
            }
        }
    }
}
