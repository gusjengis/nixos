import QtQuick
import Quickshell
import "theme"
import "bar/components"
import "menus"

// Separate surface keeps desktop interaction testable without a layer-shell window.
FocusScope {
    id: root
    property string directory: ""
    property var entries: []
    property string error: ""
    property int iconSize: 48
    property string sortBy: "name"
    property var selected: []
    property real scrollOffset: 0
    readonly property int cellWidth: Math.max(104, iconSize + 48)
    readonly property int cellHeight: iconSize + 54
    readonly property int rows: Math.max(1, Math.floor((height - Theme.barHeight - 40) / cellHeight))
    readonly property int columns: Math.ceil(ordered.length / rows)
    readonly property real maxScroll: Math.max(0, columns * cellWidth - width + 24)
    readonly property var ordered: entries.slice().sort((a, b) => {
        if (sortBy === "kind" && a.icon !== b.icon) return a.icon.localeCompare(b.icon);
        if (sortBy === "modified" && a.modified !== b.modified) return b.modified - a.modified;
        return a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
    })
    signal action(string operation, var names)
    signal iconSizeRequested(int size)
    signal sortRequested(string order)
    signal wallpaperRequested()
    // Emitted on any click; the layer requests keyboard focus only after this.
    signal interacted()
    onDirectoryChanged: { selected = []; scrollOffset = 0; menu.close(); }
    onEntriesChanged: selected = selected.filter(name => entries.some(entry => entry.name === name))
    onMaxScrollChanged: scrollOffset = Math.min(scrollOffset, maxScroll)

    function iconUrl(entry) {
        return entry.iconUrl || Quickshell.iconPath(entry.icon, true)
            || Quickshell.iconPath(entry.folder ? "folder" : "application-octet-stream");
    }
    function choose(name, modifiers) {
        if (modifiers & (Qt.ControlModifier | Qt.ShiftModifier))
            selected = selected.includes(name) ? selected.filter(item => item !== name) : selected.concat([name]);
        else selected = [name];
    }
    function openSelection() { if (selected.length) action("open", selected); }
    function showMenu(x, y, item) {
        menu.itemMenu = item;
        const point = root.mapToItem(null, x, y);
        ContextMenus.open({owner: menu, screen: root.QsWindow.window ? root.QsWindow.window.screen : Quickshell.screens[0],
            position: point, entries: menu.items.map(item => ({
                text: item.label || "", enabled: !item.separator, isSeparator: !!item.separator,
                buttonType: item.checked !== undefined ? QsMenuButtonType.CheckBox : QsMenuButtonType.None,
                checkState: item.checked ? Qt.Checked : Qt.Unchecked,
                icon: "", shortcut: item.shortcut || "", operation: item.operation, hasChildren: false
            })), activate: function(entry) { menu.activate(entry.operation); }});
    }
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Escape) { selected = []; menu.close(); }
        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) openSelection();
        else if (event.key === Qt.Key_A && event.modifiers & Qt.ControlModifier) selected = ordered.map(entry => entry.name);
        else if (event.key === Qt.Key_N && event.modifiers & Qt.ControlModifier && event.modifiers & Qt.ShiftModifier) action("new-folder", []);
        else if (event.key === Qt.Key_Delete && selected.length) action("trash", selected);
        else if ([Qt.Key_Down, Qt.Key_Up, Qt.Key_Left, Qt.Key_Right].includes(event.key)) {
            let index = ordered.findIndex(entry => entry.name === selected[selected.length - 1]);
            const delta = event.key === Qt.Key_Down ? 1 : event.key === Qt.Key_Up ? -1 : event.key === Qt.Key_Left ? rows : -rows;
            index = index < 0 ? 0 : Math.max(0, Math.min(ordered.length - 1, index + delta));
            if (ordered[index]) {
                selected = [ordered[index].name];
                const column = Math.floor(index / rows);
                scrollOffset = Math.max(0, Math.min(maxScroll, column * cellWidth - width + 2 * cellWidth));
            }
        } else { event.accepted = false; return; }
        event.accepted = true;
    }

    MouseArea {
        id: background
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        property point start: Qt.point(0, 0)
        property var previous: []
        property bool dragging: false
        onPressed: mouse => {
            root.interacted();
            root.forceActiveFocus();
            menu.close();
            if (mouse.button === Qt.RightButton) {
                root.selected = [];
                root.showMenu(mouse.x, mouse.y, false);
                return;
            }
            start = Qt.point(mouse.x, mouse.y);
            previous = mouse.modifiers & (Qt.ControlModifier | Qt.ShiftModifier) ? root.selected.slice() : [];
            root.selected = previous;
            dragging = true;
        }
        onPositionChanged: mouse => {
            if (!dragging) return;
            const names = previous.slice();
            for (let i = 0; i < icons.count; i++) {
                const item = icons.itemAt(i);
                if (item.x < Math.max(start.x, mouse.x) && item.x + item.width > Math.min(start.x, mouse.x)
                    && item.y < Math.max(start.y, mouse.y) && item.y + item.height > Math.min(start.y, mouse.y))
                    if (!names.includes(item.modelData.name)) names.push(item.modelData.name);
            }
            root.selected = names;
        }
        onReleased: dragging = false
        onCanceled: dragging = false
        onWheel: wheel => root.scrollOffset = Math.max(0, Math.min(root.maxScroll,
            root.scrollOffset - (wheel.angleDelta.x || wheel.angleDelta.y)))
    }

    Item {
        anchors.fill: parent
        clip: true
        Repeater {
            id: icons
            model: root.ordered
            delegate: Item {
                id: tile
                required property var modelData
                required property int index
                readonly property bool chosen: root.selected.includes(modelData.name)
                x: root.width - 16 - root.cellWidth * (Math.floor(index / root.rows) + 1) + root.scrollOffset
                y: Theme.barHeight + 18 + (index % root.rows) * root.cellHeight
                width: root.cellWidth
                height: root.cellHeight
                Rectangle {
                    x: (parent.width - width) / 2
                    y: 0
                    width: root.iconSize + 12; height: root.iconSize + 12
                    radius: 5
                    color: "#50000000"
                    border { width: 1; color: "#65ffffff" }
                    visible: tile.chosen
                }
                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: 6
                    width: root.iconSize; height: root.iconSize
                    source: root.iconUrl(tile.modelData)
                    sourceSize: Qt.size(root.iconSize * (root.QsWindow.window ? root.QsWindow.window.screen.devicePixelRatio : 1),
                        root.iconSize * (root.QsWindow.window ? root.QsWindow.window.screen.devicePixelRatio : 1))
                    fillMode: Image.PreserveAspectFit
                    smooth: true
                }
                Rectangle {
                    anchors { horizontalCenter: parent.horizontalCenter; top: label.top; topMargin: -1 }
                    width: Math.min(tile.width - 4, label.contentWidth + 8)
                    height: label.contentHeight + 2
                    radius: 3
                    color: "#0058d0"
                    visible: tile.chosen
                }
                Text {
                    id: label
                    x: 4; y: root.iconSize + 18
                    width: parent.width - 8
                    text: tile.modelData.displayName || tile.modelData.name
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    elide: Text.ElideRight
                    color: "white"
                    style: tile.chosen ? Text.Normal : Text.Outline
                    styleColor: "#85000000"
                    font { family: Theme.fontFamily; pixelSize: 12; weight: Font.DemiBold }
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton | Qt.RightButton
                    onPressed: mouse => {
                        root.interacted();
                        root.forceActiveFocus();
                        menu.close();
                        if (mouse.button === Qt.RightButton) {
                            if (!tile.chosen) root.selected = [tile.modelData.name];
                            const point = mapToItem(root, mouse.x, mouse.y);
                            root.showMenu(point.x, point.y, true);
                        } else root.choose(tile.modelData.name, mouse.modifiers);
                    }
                    onDoubleClicked: mouse => { if (mouse.button === Qt.LeftButton) root.openSelection(); }
                }
            }
        }
    }

    Rectangle {
        visible: background.dragging
        x: Math.min(background.start.x, background.mouseX)
        y: Math.min(background.start.y, background.mouseY)
        width: Math.abs(background.mouseX - background.start.x)
        height: Math.abs(background.mouseY - background.start.y)
        color: "#265da9ff"
        border { width: 1; color: "#99ffffff" }
    }
    Text {
        anchors { left: parent.left; bottom: parent.bottom; margins: 24 }
        visible: root.error !== ""
        text: root.error
        textFormat: Text.PlainText
        color: "white"
        style: Text.Outline; styleColor: "#aa000000"
        font { family: Theme.fontFamily; pixelSize: 12 }
    }

    Item {
        id: menu
        objectName: "desktop-context-menu"
        readonly property var node: ContextMenus.owner === menu ? ContextMenus.node : null
        function close() { ContextMenus.close(menu); }
        Component.onDestruction: close()
        property bool itemMenu: false
        property var items: itemMenu ? [
            { label: "Open", operation: "open" },
            { label: "Show Desktop Folder", operation: "folder" },
            { separator: true },
            { label: "Move to Trash", operation: "trash" }
        ] : [
            { label: "New Folder", operation: "new-folder", shortcut: "⇧⌃N" },
            { label: "Open Desktop Folder", operation: "folder" },
            { separator: true },
            { label: "Change Wallpaper…", operation: "wallpaper" },
            { separator: true },
            { label: "Sort by Name", operation: "name", checked: root.sortBy === "name" },
            { label: "Sort by Kind", operation: "kind", checked: root.sortBy === "kind" },
            { label: "Sort by Date Modified", operation: "modified", checked: root.sortBy === "modified" },
            { separator: true },
            { label: "Small Icons", operation: "small", checked: root.iconSize === 32 },
            { label: "Medium Icons", operation: "medium", checked: root.iconSize === 48 },
            { label: "Large Icons", operation: "large", checked: root.iconSize === 64 }
        ]
        function activate(operation) {
            if (operation === "wallpaper") root.wallpaperRequested();
            else if (["name", "kind", "modified"].includes(operation)) root.sortRequested(operation);
            else if (["small", "medium", "large"].includes(operation)) root.iconSizeRequested(({small: 32, medium: 48, large: 64})[operation]);
            else root.action(operation === "folder" ? "open" : operation,
                operation === "folder" || operation === "new-folder" ? [] : root.selected.slice());
        }
    }
}
