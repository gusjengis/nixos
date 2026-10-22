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

    visible: false
    focusable: true
    exclusionMode: ExclusionMode.Ignore
    anchors.top: true
    margins.top: Math.round(screen.height * 0.18)
    implicitWidth: Math.min(560, screen.width - 32)
    implicitHeight: Math.min(520, screen.height * 0.72)
    color: "transparent"
    WlrLayershell.namespace: "quickshell-session-picker"

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
            visible = false;
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
        anchors.fill: parent
        radius: Theme.panelRadius
        color: Theme.background
        border.color: Theme.border
        border.width: 1

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 20
            spacing: 12

            Text {
                text: picker.closeTarget ? "Close running session?" : picker.renameId ? "Rename session" : picker.dispensary ? "Session dispensary" : "Open sessions"
                color: Theme.text
                font { family: Theme.fontFamily; pixelSize: 22; weight: Font.DemiBold }
            }

            ThemedTextField {
                id: search
                Layout.fillWidth: true
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
                        list.currentIndex = Math.min(picker.results.length - 1, list.currentIndex + 1);
                    } else if (!picker.renameId && event.key === Qt.Key_Up) {
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
                color: Theme.muted
                wrapMode: Text.Wrap
                font { family: Theme.fontFamily; pixelSize: 13 }
            }

            ListView {
                id: list
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: !picker.renameId
                clip: true
                spacing: 4
                model: picker.results
                currentIndex: 0
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                ScrollBar.vertical: ScrollBar {}

                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: list.width
                    height: 44
                    radius: Theme.radius
                    color: list.currentIndex === index ? Theme.surfaceHover : mouse.containsMouse ? Theme.surface : "transparent"
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 12
                        Text {
                            Layout.fillWidth: true
                            text: modelData.name
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: Theme.text
                            font { family: Theme.fontFamily; pixelSize: Theme.fontSize }
                        }
                        Text {
                            text: modelData.closing ? "Closing..." : modelData.runtime_id === DesktopSessions.active ? "Active" : modelData.runtime_id ? (picker.dispensary ? "Running" : modelData.id === DesktopSessions.snapshot.previous ? "Previous" : "") : "Saved"
                            color: Theme.accent
                            font { family: Theme.fontFamily; pixelSize: 12 }
                        }
                    }
                    MouseArea {
                        id: mouse
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: !picker.closeTarget && !DesktopSessions.busy
                        onClicked: {
                            list.currentIndex = parent.index;
                            picker.submit(false);
                        }
                    }
                }
            }
        }
    }
}
