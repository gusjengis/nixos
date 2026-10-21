import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtCore
import Quickshell
import Quickshell.Hyprland
import Quickshell.Wayland
import "state"
import "theme"
import "widgets"
import "OrganizerModel.js" as Model

PanelWindow {
    id: organizer
    visible: false
    focusable: true
    exclusionMode: ExclusionMode.Ignore
    anchors.top: true
    margins.top: Math.max(40, Math.round((screen.height - implicitHeight) / 2))
    implicitWidth: Math.min(1440, screen.width - 64)
    implicitHeight: Math.min(760, screen.height - 100)
    color: "transparent"
    WlrLayershell.namespace: "quickshell-context-organizer"

    readonly property var nodes: DesktopSessions.contextCatalog.nodes || []
    readonly property bool searching: search.text.trim().length > 0
    readonly property var results: Model.search(nodes, search.text)
    property int resultIndex: 0
    property var parents: [null]
    property var choices: ({})
    property int depth: 0
    property var selectedIds: []
    property string anchorId: ""
    property var clipboard: []
    property string dialogMode: ""
    property var dialogParent: null
    property var dialogIds: []
    property var deleteLabels: []
    property int destinationIndex: 0
    property string awaiting: ""
    property string revealAfterRefresh: ""
    property string notice: ""
    property bool restoring: false
    readonly property var currentNode: searching ? results[resultIndex] || null : node(selectedIds[0])
    readonly property var currentParent: parents[Math.min(depth, parents.length - 1)] || null
    readonly property var moveChoices: [{ id: "", label: "Top level", breadcrumb: "All contexts", ancestors: [] }]
        .concat(Model.destinations(nodes, dialogIds, edit.text))

    Settings {
        id: preferences
        location: "file://" + (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/desktop-contexts/organizer.ini"
        category: "ContextOrganizer"
        property int columnWidth: 270
        property string lastSelected: ""
        property string rememberedChoices: "{}"
    }

    function node(id) { return nodes.find(item => item.id === id) || null; }
    function siblings(parent) { return Model.children(nodes, parent); }
    function remember() {
        if (restoring) return;
        preferences.rememberedChoices = JSON.stringify(choices);
        if (currentNode && !searching) preferences.lastSelected = currentNode.id;
    }
    function focusBrowse() { browse.forceActiveFocus(); }
    function ensureColumn() {
        Qt.callLater(() => {
            const left = depth * preferences.columnWidth;
            if (left < columns.contentX) columns.contentX = left;
            else if (left + preferences.columnWidth > columns.contentX + columns.width)
                columns.contentX = Math.max(0, left + preferences.columnWidth - columns.width);
        });
    }
    function select(id, column, modifiers) {
        const item = node(id);
        if (!item) return;
        const rows = siblings(item.parent_id);
        if ((modifiers & Qt.ShiftModifier) && depth === column && anchorId) {
            const from = rows.findIndex(row => row.id === anchorId);
            const to = rows.findIndex(row => row.id === id);
            selectedIds = rows.slice(Math.min(Math.max(0, from), to), Math.max(from, to) + 1).map(row => row.id);
        } else if ((modifiers & Qt.ControlModifier) && depth === column) {
            selectedIds = selectedIds.includes(id) ? selectedIds.filter(key => key !== id) : selectedIds.concat([id]);
            anchorId = id;
        } else {
            selectedIds = [id];
            anchorId = id;
        }
        choices = Object.assign({}, choices, { [item.parent_id || "root"]: id });
        depth = column;
        parents = [null].concat(item.ancestors, [id]);
        remember();
        ensureColumn();
    }
    function reveal(id) {
        const item = node(id);
        if (!item) return;
        search.text = "";
        const path = item.ancestors.concat([id]);
        const updated = Object.assign({}, choices);
        let parent = null;
        path.forEach(key => { updated[parent || "root"] = key; parent = key; });
        choices = updated;
        select(id, item.ancestors.length, 0);
        focusBrowse();
    }
    function enterColumn(column) {
        if (column < 0 || column >= parents.length) return;
        depth = column;
        const rows = siblings(parents[column]);
        const remembered = choices[parents[column] || "root"];
        if (rows.length) select((rows.find(row => row.id === remembered) || rows[0]).id, column, 0);
        else { selectedIds = []; anchorId = ""; ensureColumn(); }
        focusBrowse();
    }
    function openSelected() {
        if (!currentNode || DesktopSessions.busy) return;
        if (currentNode.is_group) {
            if (searching) reveal(currentNode.id);
            enterColumn(depth + 1);
        } else if (DesktopSessions.switchSession(currentNode.id)) awaiting = "open";
    }
    function open() {
        const monitor = Hyprland.focusedMonitor;
        const focusedScreen = Quickshell.screens.find(candidate => monitor && candidate.name === monitor.name);
        if (focusedScreen) screen = focusedScreen;
        if (nodes.length) {
            if (!currentNode && preferences.lastSelected && node(preferences.lastSelected)) reveal(preferences.lastSelected);
            else if (!currentNode && siblings(null).length) select(siblings(null)[0].id, 0, 0);
        }
        visible = true;
        focusBrowse();
    }
    function toggle() {
        if (DesktopSessions.busy) return;
        if (visible) visible = false;
        else open();
    }
    function showDialog(mode, child) {
        if (DesktopSessions.busy) return;
        if ((mode === "rename" || mode === "move" || mode === "delete") && !currentNode) return;
        dialogIds = searching && currentNode ? [currentNode.id] : selectedIds.slice();
        if (mode === "rename" && dialogIds.length !== 1) return;
        if (mode === "delete") deleteLabels = dialogIds.map(id => (node(id) || {}).breadcrumb || id);
        dialogParent = child && currentNode ? currentNode.id : searching && currentNode ? currentNode.parent_id : currentParent;
        dialogMode = mode;
        destinationIndex = 0;
        edit.text = mode === "rename" ? currentNode.label : "";
        Qt.callLater(() => {
            if (mode === "delete") cancelButton.forceActiveFocus();
            else { edit.forceActiveFocus(); if (mode === "rename") edit.selectAll(); }
        });
    }
    function closeDialog() { dialogMode = ""; focusBrowse(); }
    function editWorkingDirectory(context) {
        if (!context || context.is_group || DesktopSessions.busy) return;
        dialogIds = [context.id];
        dialogMode = "working-directory";
        edit.text = context.working_directory || ".";
        Qt.callLater(() => { edit.forceActiveFocus(); edit.selectAll(); });
    }
    function preferencesAfterDelete() {
        const updated = Object.assign({}, choices);
        Object.keys(updated).forEach(key => { if (dialogIds.includes(key) || dialogIds.includes(updated[key])) delete updated[key]; });
        choices = updated;
        preferences.lastSelected = dialogParent || "";
        search.text = "";
        if (dialogParent && node(dialogParent)) reveal(dialogParent);
        else {
            parents = [null]; depth = 0; selectedIds = [];
            const remaining = siblings(null).filter(item => !dialogIds.includes(item.id));
            if (remaining.length) select(remaining[0].id, 0, 0);
        }
    }
    function move(ids, parent) {
        if (!ids.length || DesktopSessions.busy) return false;
        const args = ids.slice();
        if (parent) args.push("--parent", parent);
        if (DesktopSessions.organize("move", args)) {
            revealAfterRefresh = ids[0];
            awaiting = "move";
            return true;
        }
        return false;
    }
    function submitDialog() {
        if (DesktopSessions.busy) return;
        if (dialogMode === "delete") {
            if (dialogIds.length && DesktopSessions.organize("delete", dialogIds.concat(["--confirm"]))) {
                awaiting = "delete";
            }
        } else if (dialogMode === "move") {
            const target = moveChoices[destinationIndex];
            if (target) move(dialogIds, target.id || null);
        } else if (dialogMode === "working-directory") {
            if (edit.text.trim() && DesktopSessions.setWorkingDirectory(dialogIds[0], edit.text.trim())) awaiting = "working-directory";
        } else if (edit.text.trim()) {
            const args = dialogMode === "create" ? [edit.text.trim()] : [dialogIds[0], edit.text.trim()];
            if (dialogMode === "create" && dialogParent) args.push("--parent", dialogParent);
            if (DesktopSessions.organize(dialogMode, args)) {
                awaiting = dialogMode;
                if (dialogMode === "rename") revealAfterRefresh = dialogIds[0];
            }
        }
    }
    function cut() {
        clipboard = searching && currentNode ? [currentNode.id] : selectedIds.slice();
        notice = clipboard.length ? clipboard.length + " selected for move. Navigate to destination, then Ctrl+V." : "";
    }
    function paste() {
        // Paste into focused column; Right enters a selected destination first.
        move(clipboard, searching && currentNode ? currentNode.id : currentParent);
    }
    function undo() {
        if (DesktopSessions.contextCatalog.can_undo && DesktopSessions.organize("undo", [])) awaiting = "undo";
    }
    function promote() {
        if (currentNode && currentNode.is_group && DesktopSessions.organize("promote", [currentNode.id])) awaiting = "promote";
    }
    function handleKey(event) {
        if (dialogMode || DesktopSessions.busy) return;
        const ctrl = (event.modifiers & Qt.ControlModifier) !== 0;
        if (event.key === Qt.Key_Escape) {
            if (searching) { search.text = ""; focusBrowse(); }
            else if (clipboard.length) { clipboard = []; notice = ""; }
            else visible = false;
        } else if (ctrl && event.key === Qt.Key_F) { search.forceActiveFocus(); search.selectAll(); }
        else if (ctrl && event.key === Qt.Key_N) showDialog("create", (event.modifiers & Qt.ShiftModifier) !== 0);
        else if (event.key === Qt.Key_F2) showDialog("rename", false);
        else if (ctrl && event.key === Qt.Key_X) cut();
        else if (ctrl && event.key === Qt.Key_V) paste();
        else if (ctrl && event.key === Qt.Key_Z) undo();
        else if (ctrl && event.key === Qt.Key_M) showDialog("move", false);
        else if (ctrl && event.key === Qt.Key_D) { if (!event.isAutoRepeat) showDialog("delete", false); }
        else if (ctrl && event.key === Qt.Key_A) {
            if (searching) return;
            selectedIds = siblings(currentParent).map(item => item.id);
        } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) openSelected();
        else if (event.key === Qt.Key_Right) {
            if (searching && currentNode) reveal(currentNode.id);
            else enterColumn(depth + 1);
        } else if (event.key === Qt.Key_Left) {
            if (searching) return;
            enterColumn(depth - 1);
        } else if (event.key === Qt.Key_Down || event.key === Qt.Key_Up) {
            const delta = event.key === Qt.Key_Down ? 1 : -1;
            if (searching) resultIndex = Math.max(0, Math.min(results.length - 1, resultIndex + delta));
            else {
                const rows = siblings(currentParent);
                const index = rows.findIndex(item => item.id === choices[currentParent || "root"]);
                const target = rows[Math.max(0, Math.min(rows.length - 1, index + delta))];
                if (target) select(target.id, depth, event.modifiers & Qt.ShiftModifier);
            }
        } else if (!ctrl && event.text && event.text.trim() && !search.activeFocus) {
            search.forceActiveFocus(); search.text += event.text;
        } else return;
        event.accepted = true;
    }

    Component.onCompleted: {
        restoring = true;
        try { choices = JSON.parse(preferences.rememberedChoices); } catch (_) { choices = ({}); }
        restoring = false;
    }
    onNodesChanged: {
        if (revealAfterRefresh && node(revealAfterRefresh)) {
            const id = revealAfterRefresh; revealAfterRefresh = ""; reveal(id);
        } else if (!searching && selectedIds.length && node(selectedIds[0])) {
            // Refresh the ancestor path after remote or batch organization.
            const selected = selectedIds.slice();
            const item = node(selected[0]);
            const path = [null].concat(item.ancestors, [item.id]);
            if (JSON.stringify(path) !== JSON.stringify(parents)) {
                select(item.id, item.ancestors.length, 0);
                selectedIds = selected.filter(id => node(id) && node(id).parent_id === item.parent_id);
            }
        } else if (!searching && parents.some(id => id && !node(id))) {
            parents = [null]; depth = 0; selectedIds = [];
        }
        if (visible && !currentNode && nodes.length && !searching && parents.length === 1) {
            if (preferences.lastSelected && node(preferences.lastSelected)) reveal(preferences.lastSelected);
            else if (siblings(null).length) select(siblings(null)[0].id, 0, 0);
        }
    }
    Connections {
        target: DesktopSessions
        function onCompleted(action) {
            if (!organizer.awaiting) return;
            const completed = organizer.awaiting;
            organizer.awaiting = "";
            if (completed === "open") { organizer.visible = false; return; }
            if (completed === "create" || completed === "promote") organizer.revealAfterRefresh = DesktopSessions.createdContextId;
            if (completed === "move") { organizer.clipboard = []; organizer.notice = "Contexts moved."; }
            else if (completed === "delete") {
                organizer.notice = "Selected contexts moved to Trash.";
                organizer.clipboard = organizer.clipboard.filter(id => !organizer.dialogIds.includes(id));
                organizer.selectedIds = organizer.selectedIds.filter(id => !organizer.dialogIds.includes(id));
                organizer.preferencesAfterDelete();
            }
            else if (completed === "undo") organizer.notice = "Organization change undone.";
            else if (completed === "working-directory") organizer.notice = "Working directory updated. Existing terminals keep their current directories.";
            else organizer.notice = completed === "create" || completed === "promote" ? "Context created. Enter opens it." : "Context renamed.";
            organizer.closeDialog();
            if (organizer.revealAfterRefresh && organizer.node(organizer.revealAfterRefresh)) {
                const id = organizer.revealAfterRefresh; organizer.revealAfterRefresh = ""; organizer.reveal(id);
            }
        }
        function onFailed() { organizer.awaiting = ""; }
    }

    HyprlandFocusGrab {
        id: grab
        windows: [organizer]
        onCleared: {
            if (!FocusGuard.suspended && !DesktopSessions.busy && !organizer.dialogMode && !DesktopSessions.error)
                organizer.visible = false;
        }
    }
    Binding { target: grab; property: "active"; value: organizer.visible && !FocusGuard.suspended }

    Rectangle {
        anchors.fill: parent
        radius: 15
        color: "#242731"
        border.color: "#525561"
        clip: true

        FocusScope {
            id: browse
            anchors.fill: parent
            focus: true
            Keys.onPressed: event => organizer.handleKey(event)

            ColumnLayout {
                anchors.fill: parent
                spacing: 0

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 64
                    color: "#30333e"
                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 15
                        spacing: 10
                        Rectangle {
                            width: 13; height: 13; radius: 7; color: "#ff625c"
                            MouseArea { anchors.fill: parent; onClicked: organizer.visible = false }
                        }
                        Text { text: "Contexts"; color: "#f1f2f6"; font { family: Theme.fontFamily; pixelSize: 18; weight: Font.DemiBold } }
                        Item { Layout.fillWidth: true }
                        ThemedTextField {
                            id: search
                            Layout.preferredWidth: Math.min(340, organizer.width * 0.25)
                            placeholderText: "Search all contexts…"
                            onTextChanged: organizer.resultIndex = 0
                            Keys.onPressed: event => {
                                if (event.key === Qt.Key_Left || event.key === Qt.Key_Right) {
                                    if (event.key === Qt.Key_Left && organizer.searching) return;
                                }
                                organizer.handleKey(event);
                            }
                        }
                        OrganizerButton { text: "↶ Undo"; enabled: !!DesktopSessions.contextCatalog.can_undo && !DesktopSessions.busy; onClicked: organizer.undo() }
                        OrganizerButton { text: "+ New context"; primary: true; enabled: !DesktopSessions.busy; onClicked: organizer.showDialog("create", false) }
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 44
                    color: "#292d37"
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 20; anchors.rightMargin: 20
                        Text { text: organizer.searching ? "Search results" : "All contexts"; color: "#aeb5c6"; font { family: Theme.fontFamily; pixelSize: 13 }
                            MouseArea { anchors.fill: parent; onClicked: { search.text = ""; organizer.parents = [null]; organizer.enterColumn(0); } }
                        }
                        Text { text: organizer.currentNode ? "›  " + organizer.currentNode.breadcrumb : ""; color: "#e3e7ef"; elide: Text.ElideLeft; Layout.fillWidth: true; font { family: Theme.fontFamily; pixelSize: 13 } }
                        Text { text: "−"; color: "#c7cddb"; font.pixelSize: 22; MouseArea { anchors.fill: parent; onClicked: preferences.columnWidth = Math.max(210, preferences.columnWidth - 30) } }
                        Text { text: "Column width"; color: "#929bad"; font.pixelSize: 12 }
                        Text { text: "+"; color: "#c7cddb"; font.pixelSize: 20; MouseArea { anchors.fill: parent; onClicked: preferences.columnWidth = Math.min(480, preferences.columnWidth + 30) } }
                    }
                }

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    Flickable {
                        id: columns
                        anchors.fill: parent
                        anchors.rightMargin: directoryPreview.width
                        visible: !organizer.searching
                        clip: true
                        contentWidth: columnRow.width
                        contentHeight: height
                        boundsBehavior: Flickable.StopAtBounds
                        flickableDirection: Flickable.HorizontalFlick
                        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                        Row {
                            id: columnRow
                            height: columns.height
                            Repeater {
                                // A count model keeps source delegates alive during
                                // selection/drag; replacing an array model destroys them.
                                model: organizer.parents.length
                                delegate: Rectangle {
                                    id: column
                                    required property int index
                                    readonly property var modelData: organizer.parents[index]
                                    readonly property var rows: organizer.siblings(modelData)
                                    width: preferences.columnWidth
                                    height: columnRow.height
                                    color: index === organizer.depth ? "#252a35" : "#282c36"
                                    border.color: "#393f4c"
                                    border.width: 0.5

                                    DropArea {
                                        anchors.fill: parent
                                        keys: ["desktop-contexts"]
                                        onDropped: drop => { if (drop.source) { organizer.move(drop.source.contextIds, column.modelData); drop.acceptProposedAction(); } }
                                    }
                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 8
                                        spacing: 6
                                        Text {
                                            Layout.fillWidth: true
                                            Layout.leftMargin: 7
                                            Layout.preferredHeight: 30
                                            text: column.modelData ? (organizer.node(column.modelData) || {}).label || "Missing context" : "All contexts"
                                            color: column.index === organizer.depth ? "#becce3" : "#8e98ac"
                                            font { family: Theme.fontFamily; pixelSize: 12; weight: Font.DemiBold }
                                            elide: Text.ElideRight
                                            verticalAlignment: Text.AlignVCenter
                                            MouseArea { anchors.fill: parent; onClicked: organizer.enterColumn(column.index) }
                                        }
                                        ListView {
                                            id: rowsList
                                            Layout.fillWidth: true
                                            Layout.fillHeight: true
                                            clip: true
                                            spacing: 3
                                            model: column.rows
                                            currentIndex: column.rows.findIndex(row => row.id === organizer.choices[column.modelData || "root"])
                                            onCurrentIndexChanged: if (currentIndex >= 0) positionViewAtIndex(currentIndex, ListView.Contain)
                                            ScrollBar.vertical: ScrollBar {}
                                            delegate: Rectangle {
                                                id: row
                                                required property var modelData
                                                required property int index
                                                readonly property bool chosen: column.index === organizer.depth && organizer.selectedIds.includes(modelData.id)
                                                readonly property bool onPath: organizer.parents.includes(modelData.id)
                                                width: rowsList.width
                                                height: 38
                                                radius: 6
                                                color: chosen ? "#3478cf" : onPath ? "#414958" : mouse.containsMouse ? "#343b48" : "transparent"
                                                opacity: organizer.clipboard.includes(modelData.id) ? 0.5 : 1

                                                RowLayout {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: 10; anchors.rightMargin: 9
                                                    spacing: 8
                                                    Text { text: row.modelData.is_group || row.modelData.child_count ? "▱" : "▣"; color: row.chosen ? "#d6e8ff" : "#94b9e8"; font.pixelSize: 21 }
                                                    Text { text: row.modelData.label; color: "#eef1f6"; Layout.fillWidth: true; elide: Text.ElideRight; font { family: Theme.fontFamily; pixelSize: 14 } }
                                                    Text { visible: !!row.modelData.unplaced; text: "!"; color: "#f3c77e"; font.pixelSize: 14 }
                                                    Rectangle { visible: !!row.modelData.runtime_id; width: 6; height: 6; radius: 3; color: "#9ee5bc" }
                                                    Text { visible: row.modelData.child_count > 0; text: "›"; color: "#bdc9db"; font.pixelSize: 22 }
                                                }
                                                Rectangle {
                                                    id: dragToken
                                                    parent: organizer.contentItem
                                                    property var contextIds: []
                                                    x: 0; y: 0
                                                    width: 180; height: 32; radius: 6
                                                    color: "#3478cf"
                                                    visible: mouse.drag.active
                                                    z: 1000
                                                    Drag.active: mouse.drag.active
                                                    Drag.source: dragToken
                                                    Drag.keys: ["desktop-contexts"]
                                                    Drag.supportedActions: Qt.MoveAction
                                                    Drag.hotSpot.x: mouse.grabX
                                                    Drag.hotSpot.y: mouse.grabY
                                                    Text { anchors.centerIn: parent; text: dragToken.contextIds.length + " context(s)"; color: "white"; font.pixelSize: 13 }
                                                }
                                                MouseArea {
                                                    id: mouse
                                                    anchors.fill: parent
                                                    hoverEnabled: true
                                                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                                                    drag.target: dragToken
                                                    drag.threshold: 8
                                                    property real grabX: 0
                                                    property real grabY: 0
                                                    onPressed: event => {
                                                        grabX = event.x; grabY = event.y;
                                                        const position = row.mapToItem(organizer.contentItem, 0, 0);
                                                        dragToken.x = position.x; dragToken.y = position.y;
                                                        if (!row.chosen || event.modifiers) organizer.select(row.modelData.id, column.index, event.modifiers);
                                                        organizer.focusBrowse();
                                                        dragToken.contextIds = organizer.selectedIds.slice();
                                                        if (event.button === Qt.RightButton) organizer.showDialog("move", false);
                                                    }
                                                    onClicked: event => { if (event.button === Qt.LeftButton && !event.modifiers) organizer.select(row.modelData.id, column.index, 0); }
                                                    onDoubleClicked: organizer.openSelected()
                                                    onReleased: {
                                                        if (drag.active) {
                                                            dragToken.Drag.drop();
                                                            if (!organizer.awaiting) organizer.reveal(row.modelData.id);
                                                        }
                                                    }
                                                    onCanceled: if (!organizer.awaiting && organizer.visible) organizer.reveal(row.modelData.id)
                                                }
                                                DropArea {
                                                    anchors.fill: parent
                                                    keys: ["desktop-contexts"]
                                                    onEntered: hoverOpen.restart()
                                                    onExited: hoverOpen.stop()
                                                    onDropped: drop => {
                                                        hoverOpen.stop();
                                                        if (drop.source) { organizer.move(drop.source.contextIds, row.modelData.id); drop.acceptProposedAction(); }
                                                    }
                                                    Timer {
                                                        id: hoverOpen
                                                        interval: 650
                                                        onTriggered: {
                                                            const item = organizer.node(row.modelData.id);
                                                            if (item && !organizer.parents.includes(item.id)) {
                                                                // Keep source columns alive while they own the
                                                                // mouse grab. Normalize the path after drop.
                                                                organizer.parents = organizer.parents.concat([item.id]);
                                                                Qt.callLater(() => columns.contentX = Math.max(0, columns.contentWidth - columns.width));
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            Text {
                                                anchors.centerIn: parent
                                                visible: !column.rows.length
                                                text: "No children yet\n\nDrop contexts here, or create one."
                                                width: parent.width - 20
                                                wrapMode: Text.Wrap
                                                horizontalAlignment: Text.AlignHCenter
                                                color: "#818da3"
                                                font { family: Theme.fontFamily; pixelSize: 13 }
                                            }
                                        }
                                        OrganizerButton {
                                            text: "+ New here"
                                            Layout.fillWidth: true
                                            enabled: !DesktopSessions.busy
                                            onClicked: { organizer.depth = column.index; organizer.showDialog("create", false); }
                                        }
                                    }
                                    Rectangle {
                                        anchors.right: parent.right
                                        width: 5; height: parent.height
                                        color: resize.containsMouse ? "#7197c6" : "transparent"
                                        MouseArea {
                                            id: resize
                                            anchors.fill: parent
                                            hoverEnabled: true
                                            cursorShape: Qt.SplitHCursor
                                            property real startX: 0
                                            property int startWidth: 0
                                            onPressed: event => { startX = mapToItem(organizer.contentItem, event.x, event.y).x; startWidth = preferences.columnWidth; }
                                            onPositionChanged: event => {
                                                if (pressed) preferences.columnWidth = Math.max(210, Math.min(480, startWidth + mapToItem(organizer.contentItem, event.x, event.y).x - startX));
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }

                    ListView {
                        id: searchResults
                        anchors.fill: parent
                        anchors.margins: 12
                        anchors.rightMargin: directoryPreview.width + 12
                        visible: organizer.searching
                        clip: true
                        spacing: 4
                        model: organizer.results
                        currentIndex: organizer.resultIndex
                        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                        ScrollBar.vertical: ScrollBar {}
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            width: searchResults.width
                            height: 62
                            radius: 7
                            color: index === organizer.resultIndex ? "#354d71" : resultMouse.containsMouse ? "#303744" : "transparent"
                            Column {
                                anchors.left: parent.left; anchors.leftMargin: 15; anchors.verticalCenter: parent.verticalCenter
                                spacing: 4
                                Text { text: Model.highlights(modelData.label, search.text); textFormat: Text.RichText; color: "#f0f2f6"; font { family: Theme.fontFamily; pixelSize: 15 } }
                                Text { text: modelData.breadcrumb; color: "#9eacc2"; font { family: Theme.fontFamily; pixelSize: 12 } }
                            }
                            Text { anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter; text: modelData.runtime_id ? "Running" : modelData.is_group ? "Group" : "Saved"; color: "#a4c4ee"; font.pixelSize: 12 }
                            MouseArea { id: resultMouse; anchors.fill: parent; hoverEnabled: true; onClicked: organizer.resultIndex = index; onDoubleClicked: { organizer.resultIndex = index; organizer.reveal(modelData.id); } }
                        }
                        Text { anchors.centerIn: parent; visible: !organizer.results.length; text: "No matching contexts"; color: "#9aa6ba"; font.pixelSize: 16 }
                    }
                    Text { anchors.centerIn: parent; visible: !organizer.nodes.length; text: "No saved contexts yet. Create your first context above."; color: "#aab5c8"; font.pixelSize: 16 }
                    WorkingDirectoryPreview {
                        id: directoryPreview
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        anchors.right: parent.right
                        width: Math.min(600, parent.width * 0.42)
                        readonly property var context: organizer.currentNode || organizer.node(organizer.currentParent)
                        directory: context ? context.cwd || context.path || "" : ""
                        configuredDirectory: context ? context.working_directory || directory : ""
                        targetDirectory: context ? context.working_directory_path || directory : ""
                        directoryAvailable: !context || context.working_directory_available !== false
                        editable: !!context && !context.is_group && !DesktopSessions.busy
                        onEditRequested: organizer.editWorkingDirectory(context)
                        active: organizer.visible
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: 61
                    color: "#2c303b"
                    RowLayout {
                        anchors.fill: parent; anchors.margins: 13; spacing: 9
                        OrganizerButton { text: "Open"; primary: true; enabled: !!organizer.currentNode && !DesktopSessions.busy; onClicked: organizer.openSelected() }
                        OrganizerButton { text: "New child"; enabled: !!organizer.currentNode && !DesktopSessions.busy; onClicked: organizer.showDialog("create", true) }
                        OrganizerButton { text: "Make context"; visible: !!organizer.currentNode && organizer.currentNode.is_group; enabled: !DesktopSessions.busy; onClicked: organizer.promote() }
                        OrganizerButton { text: "Rename"; enabled: !!organizer.currentNode && (organizer.searching || organizer.selectedIds.length === 1) && !DesktopSessions.busy; onClicked: organizer.showDialog("rename", false) }
                        OrganizerButton { text: "Move to…"; enabled: !!organizer.currentNode && !DesktopSessions.busy; onClicked: organizer.showDialog("move", false) }
                        OrganizerButton { text: "Delete…"; enabled: !!organizer.currentNode && !DesktopSessions.busy; onClicked: organizer.showDialog("delete", false) }
                        OrganizerButton { text: "Paste here"; visible: organizer.clipboard.length > 0; enabled: !DesktopSessions.busy; onClicked: organizer.paste() }
                        Item { Layout.fillWidth: true }
                        Text {
                            text: DesktopSessions.busy ? "Applying change…" : organizer.searching ? organizer.results.length + " matches" : organizer.selectedIds.length > 1 ? organizer.selectedIds.length + " selected" : "← → Explore   ↑ ↓ Select   Enter Open"
                            color: "#a3aec2"; font { family: Theme.fontFamily; pixelSize: 12 }
                        }
                    }
                }
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: DesktopSessions.error ? 58 : 33
                    color: "#242832"
                    Text {
                        anchors.fill: parent; anchors.leftMargin: 17; anchors.rightMargin: 40
                        verticalAlignment: Text.AlignVCenter
                        text: DesktopSessions.error || organizer.notice || "Type to search · Ctrl+N New · F2 Rename · Ctrl+M Move · Ctrl+D Delete · Ctrl+X / Ctrl+V Cut/Paste · Ctrl+Z Undo"
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: DesktopSessions.error ? "#f2a5a5" : "#8e9ab0"
                        font { family: Theme.fontFamily; pixelSize: 12 }
                    }
                    Text {
                        anchors.right: parent.right; anchors.rightMargin: 15; anchors.verticalCenter: parent.verticalCenter
                        text: "×"; visible: !!DesktopSessions.error || !!organizer.notice; color: "#b9c3d5"; font.pixelSize: 19
                        MouseArea { anchors.fill: parent; onClicked: { DesktopSessions.error = ""; organizer.notice = ""; } }
                    }
                }
            }
        }

        Rectangle {
            anchors.fill: parent
            visible: organizer.dialogMode !== ""
            color: "#a510131b"
            z: 100
            MouseArea { anchors.fill: parent; onClicked: if (!DesktopSessions.busy) organizer.closeDialog() }
            Rectangle {
                width: Math.min(620, parent.width - 60)
                height: organizer.dialogMode === "move" ? Math.min(530, parent.height - 60) : organizer.dialogMode === "delete" ? Math.min(400, parent.height - 60) : 268
                anchors.centerIn: parent
                radius: 14
                color: "#303540"
                border.color: "#616b7d"
                Keys.onEscapePressed: if (!DesktopSessions.busy) organizer.closeDialog()
                MouseArea { anchors.fill: parent }
                ColumnLayout {
                    anchors.fill: parent; anchors.margins: 23; spacing: 14
                    Text { text: organizer.dialogMode === "create" ? "New context" : organizer.dialogMode === "working-directory" ? "Working directory" : organizer.dialogMode === "rename" ? "Rename context" : organizer.dialogMode === "delete" ? "Move " + organizer.dialogIds.length + " context(s) to Trash?" : "Move " + organizer.dialogIds.length + " context(s)"; color: "#f1f3f8"; font { family: Theme.fontFamily; pixelSize: 22; weight: Font.DemiBold } }
                    Text {
                        Layout.fillWidth: true
                        text: organizer.dialogMode === "create" ? "In: " + (organizer.node(organizer.dialogParent) || { breadcrumb: "All contexts" }).breadcrumb
                            : organizer.dialogMode === "rename" ? "Changes display name. Files and running session stay in place."
                            : organizer.dialogMode === "working-directory" ? "Relative to context folder, or an absolute path. Use . for context folder."
                            : organizer.dialogMode === "delete" ? "Context directories, working files, notebooks and saved state move to system Trash. Restore them through your file manager. Close running contexts and move children out first."
                            : "Choose destination. Descendants move with their parent."
                        wrapMode: organizer.dialogMode === "delete" || organizer.dialogMode === "working-directory" ? Text.Wrap : Text.NoWrap
                        elide: Text.ElideMiddle; color: "#aebbd0"; font { family: Theme.fontFamily; pixelSize: 13 }
                    }
                    Flickable {
                        Layout.fillWidth: true; Layout.fillHeight: true
                        visible: organizer.dialogMode === "delete"
                        clip: true
                        contentHeight: deleteNames.implicitHeight
                        ScrollBar.vertical: ScrollBar {}
                        Text {
                            id: deleteNames
                            width: parent.width
                            text: "• " + organizer.deleteLabels.join("\n• ")
                            textFormat: Text.PlainText
                            wrapMode: Text.WrapAnywhere
                            color: "#edf0f7"
                            font { family: Theme.fontFamily; pixelSize: 14 }
                        }
                    }
                    ThemedTextField {
                        id: edit
                        visible: organizer.dialogMode !== "delete"
                        Layout.fillWidth: true
                        placeholderText: organizer.dialogMode === "move" ? "Find destination…" : organizer.dialogMode === "working-directory" ? "., MyRepo, or /etc/nixos" : "Context name"
                        readOnly: DesktopSessions.busy
                        onTextChanged: organizer.destinationIndex = 0
                        Keys.onPressed: event => {
                            if (event.key === Qt.Key_Escape) { if (!DesktopSessions.busy) organizer.closeDialog(); }
                            else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) organizer.submitDialog();
                            else if (organizer.dialogMode === "move" && event.key === Qt.Key_Down) organizer.destinationIndex = Math.min(organizer.moveChoices.length - 1, organizer.destinationIndex + 1);
                            else if (organizer.dialogMode === "move" && event.key === Qt.Key_Up) organizer.destinationIndex = Math.max(0, organizer.destinationIndex - 1);
                            else return;
                            event.accepted = true;
                        }
                    }
                    ListView {
                        id: destinations
                        Layout.fillWidth: true; Layout.fillHeight: true
                        visible: organizer.dialogMode === "move"
                        clip: true; spacing: 3
                        model: organizer.moveChoices
                        currentIndex: organizer.destinationIndex
                        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
                        ScrollBar.vertical: ScrollBar {}
                        delegate: Rectangle {
                            required property var modelData
                            required property int index
                            width: destinations.width; height: 45; radius: 6
                            color: index === organizer.destinationIndex ? "#3e5c86" : "transparent"
                            Text { anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; verticalAlignment: Text.AlignVCenter; text: modelData.breadcrumb; elide: Text.ElideMiddle; color: "#e5ecf7"; font { family: Theme.fontFamily; pixelSize: 13 } }
                            MouseArea { anchors.fill: parent; onClicked: { organizer.destinationIndex = index; edit.forceActiveFocus(); } onDoubleClicked: { organizer.destinationIndex = index; organizer.submitDialog(); } }
                        }
                    }
                    Text { Layout.fillWidth: true; visible: !!DesktopSessions.error; text: DesktopSessions.error; wrapMode: Text.Wrap; maximumLineCount: 3; elide: Text.ElideRight; color: "#f2a5a5"; font.pixelSize: 12 }
                    Item { Layout.fillHeight: true; visible: organizer.dialogMode !== "move" && organizer.dialogMode !== "delete" }
                    RowLayout {
                        Item { Layout.fillWidth: true }
                        OrganizerButton { id: cancelButton; text: "Cancel"; enabled: !DesktopSessions.busy; onClicked: organizer.closeDialog(); Keys.onReturnPressed: organizer.closeDialog() }
                        OrganizerButton {
                            text: DesktopSessions.busy ? "Applying…" : organizer.dialogMode === "working-directory" ? "Save" : organizer.dialogMode === "create" ? "Create" : organizer.dialogMode === "rename" ? "Rename" : organizer.dialogMode === "delete" ? "Move to Trash" : "Move"
                            primary: true
                            destructive: organizer.dialogMode === "delete"
                            enabled: !DesktopSessions.busy && (organizer.dialogMode === "move" || organizer.dialogMode === "delete" ? organizer.dialogIds.length > 0 : !!edit.text.trim())
                            onClicked: organizer.submitDialog()
                            Keys.onReturnPressed: organizer.submitDialog()
                        }
                    }
                }
            }
        }
    }
}
