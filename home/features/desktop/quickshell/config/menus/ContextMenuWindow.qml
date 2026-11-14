import QtQuick
import Quickshell
import Quickshell.Hyprland
import "../state"
import "../theme"
import "../bar/components"

// One menu level. Root owns one linear branch and one grab covering every level.
// QsMenuOpener retains live D-Bus entries; snapshot callers supply plain entries.
GuardedPopupWindow {
    id: node
    property var entries: []
    property var source: null
    property var nodeFactory: null
    property var rootNode: node
    property var parentMenu: null
    property int parentIndex: -1
    property bool isRoot: true
    property bool keyboardDriven: false
    property var leafHandler: null
    property var cancelHandler: null
    property var liveNodes: []
    property int currentIndex: -1
    property bool closing: false
    property bool requested: false
    property bool prepared: false
    property int layoutRevision: 0
    readonly property font textFont: Theme.menuFont
    readonly property int textRenderType: Text.NativeRendering
    readonly property var values: source ? (opener.children ? opener.children.values : []) : entries
    readonly property var listModel: source ? opener.children : entries
    readonly property bool reserveLeading: values.some(e => e && !e.isSeparator &&
        e.buttonType !== undefined && e.buttonType !== QsMenuButtonType.None)
    signal finished()

    popupWidth: {
        // Dock menus shrink to their content (Trash: 108 pt on macOS 27). AppKit
        // reserves a submenu-arrow column on every row (Calculator "Options ▸": 110 pt).
        let width = callout ? 0 : 160;
        const arrowColumn = callout && values.some(entry => entry && !entry.isSeparator && entry.hasChildren) ? 30.5 : 0;
        for (const entry of values) {
            if (!entry || entry.isSeparator) continue;
            width = Math.max(width, metrics.advanceWidth(label(entry)) +
                (entry.shortcut ? metrics.advanceWidth(entry.shortcut) + 24 : 0) +
                2 * Theme.menuTextInset + (reserveLeading ? 14 : 0) + (entry.icon ? 21 : 0) + (callout ? arrowColumn : 20));
        }
        return Math.min(callout ? Math.ceil(width) : width, screen ? screen.width - 2 * Theme.popupScreenMargin : 560);
    }
    popupHeight: Math.max(2 * Theme.menuPadding,
        Math.min(values.reduce((height, entry) => height + (entry.isSeparator ? Theme.menuSeparatorHeight : Theme.menuRowHeight), 2 * Theme.menuPadding),
            (screen ? screen.height : 720) - 2 * Theme.popupScreenMargin))
    focusGrabEnabled: false
    popupX: anchorItem ? anchorItem.width - popupWidth : 0
    absolutePosition: parentMenu ? childPosition() : callout ? calloutPosition() : null
    // Dock menus: {x, bottom} in screen coordinates. The pointer tip sits at x,
    // 27 pt from the body's left edge (right edge when that would leave the screen).
    property var callout: null
    readonly property int calloutInset: 27
    readonly property bool calloutEnd: !!callout && !!screen &&
        callout.x - calloutInset + popupWidth > screen.width - Theme.popupScreenMargin
    glassNamespace: !callout ? "quickshell-menu" : calloutEnd ? "quickshell-dock-menu-end" : "quickshell-dock-menu"
    calloutHeight: callout ? 10 : 0
    function calloutPosition() {
        return Qt.point(calloutEnd ? callout.x + calloutInset - popupWidth : callout.x - calloutInset,
            callout.bottom - popupHeight);
    }

    QsMenuOpener { id: opener; menu: node.source }
    FontMetrics { id: metrics; font: node.textFont }
    HyprlandFocusGrab {
        active: node.isRoot && node.visible && !node.closing && !FocusGuard.suspended
        windows: node.isRoot ? [node].concat(node.liveNodes) : []
        onCleared: {
            if (node.isRoot && !FocusGuard.suspended) node.closeCascade(true);
        }
    }
    FocusScope {
        id: keyScope
        anchors.fill: parent
        focus: true
        Keys.onPressed: event => node.rootNode._key(event)
        ListView {
            id: list
            anchors { fill: parent; margins: Theme.menuPadding }
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: node.listModel
            delegate: ContextMenuRow {
                id: row
                required property var modelData
                required property int index
                width: list ? list.width : 0
                entry: modelData
                reserveLeading: !!node && node.reserveLeading
                stripMnemonics: !!node && node.source !== null
                textFont: node ? node.textFont : Theme.menuFont
                textRenderType: node ? node.textRenderType : Text.NativeRendering
                keyboardHighlighted: !!node && node.currentIndex === index
                onHovered: if (node) node.hoverRow(index)
                onHoverEnded: if (node) node.cancelSpawn(index)
                onActivated: if (node) node.activateIndex(index)
            }
            onCountChanged: {
                if (node.keyboardDriven && node.currentIndex < 0) node.selectFirst();
            }
        }
    }
    Timer {
        id: spawnTimer
        interval: 150
        property int targetIndex: -1
        onTriggered: {
            const index = targetIndex;
            targetIndex = -1;
            if (!node.visible) return;
            const entry = node.entryAt(index);
            if (entry && entry.enabled && entry.hasChildren)
                node.rootNode.spawnNode(node, index, entry);
            else node.rootNode.trimAfter(node);
        }
    }
    Timer { id: searchTimer; interval: 700; onTriggered: node.search = "" }
    property string search: ""
    Component.onCompleted: if (keyboardDriven) Qt.callLater(selectFirst)
    onValuesChanged: prepare()
    Connections {
        target: Theme
        function onGlassStatusKnownChanged() { node.prepare(); }
    }
    Component.onDestruction: {
        for (const child of liveNodes) child.destroy();
    }

    function label(entry) {
        return source ? entry.text.replace(/&&/g, "\u0000").replace(/&/g, "").replace(/\u0000/g, "&") : entry.text || "";
    }
    function present() {
        requested = true;
        prepare();
    }
    function prepare() {
        if (!requested || closing || prepared || !values.length || !Theme.glassStatusKnown) return;
        const revision = ++layoutRevision;
        // D-Bus arrives asynchronously. Never map an empty layer surface or
        // expose its intermediate geometry. Flush delegates while still hidden,
        // then allow bindings/polish to settle before the first surface commit.
        Qt.callLater(function() {
            if (closing || revision !== layoutRevision) return;
            list.forceLayout();
            Qt.callLater(function() {
                if (closing || revision !== layoutRevision || !values.length) return;
                list.forceLayout();
                node._place();
                prepared = true;
                visible = true;
                if (isRoot || keyboardDriven) grabFocus();
            });
        });
    }
    function entryAt(index) { return index >= 0 && index < values.length ? values[index] : null; }
    function tipNode() { return liveNodes.length ? liveNodes[liveNodes.length - 1] : node; }
    function rowAt(index) { return list.itemAtIndex(index); }
    function rowOffset(index) {
        // Works before delegates are polished, and for rows outside the viewport.
        let y = Theme.menuPadding - list.contentY;
        for (let i = 0; i < index; ++i)
            y += values[i].isSeparator ? Theme.menuSeparatorHeight : Theme.menuRowHeight;
        return y;
    }
    function childPosition() {
        const parent = parentMenu;
        const right = parent._origin.x + parent.popupWidth - Theme.menuPadding;
        const left = parent._origin.x - popupWidth + Theme.menuPadding;
        const max = screen ? screen.width - Theme.popupScreenMargin : right + popupWidth;
        return Qt.point(right + popupWidth <= max ? right : left,
            parent._origin.y + parent.rowOffset(parentIndex) - Theme.menuPadding);
    }
    function setHighlight(index) {
        currentIndex = index;
        if (index >= 0) list.positionViewAtIndex(index, ListView.Contain);
    }
    function selectFirst() {
        for (let i = 0; i < values.length; ++i) {
            if (values[i].enabled && !values[i].isSeparator) { setHighlight(i); return; }
        }
    }
    function moveHighlight(step) {
        cancelSpawn();
        const start = currentIndex < 0 ? (step > 0 ? -1 : 0) : currentIndex;
        for (let n = 1; n <= values.length; ++n) {
            const i = (start + step * n + values.length) % values.length;
            if (values[i].enabled && !values[i].isSeparator) {
                rootNode.trimAfter(node);
                setHighlight(i);
                return;
            }
        }
    }
    function typeAhead(text) {
        search += text.toLowerCase();
        searchTimer.restart();
        for (let n = 1; n <= values.length; ++n) {
            const i = (Math.max(-1, currentIndex) + n) % values.length;
            if (values[i].enabled && !values[i].isSeparator && label(values[i]).toLowerCase().startsWith(search)) {
                rootNode.trimAfter(node);
                setHighlight(i);
                return;
            }
        }
    }
    function grabFocus() { Qt.callLater(function() { if (node.visible) keyScope.forceActiveFocus(); }); }
    function hoverRow(index) {
        currentIndex = index;
        spawnTimer.targetIndex = index;
        spawnTimer.restart();
    }
    function cancelSpawn(index) {
        if (index !== undefined && spawnTimer.targetIndex !== index) return;
        spawnTimer.stop();
        spawnTimer.targetIndex = -1;
    }
    function trimAfter(parent) {
        const depth = parent === node ? 0 : liveNodes.indexOf(parent) + 1;
        if (parent !== node && depth === 0) return;
        const removed = liveNodes.slice(depth);
        liveNodes = liveNodes.slice(0, depth);
        for (const child of removed) { child.visible = false; child.destroy(); }
    }
    function spawnNode(parent, index, entry, keyboard) {
        if (!isRoot || closing || !entry || !entry.enabled || !entry.hasChildren) return;
        const depth = parent === node ? 0 : liveNodes.indexOf(parent) + 1;
        if (parent !== node && depth === 0) return;
        const previous = liveNodes[depth];
        if (previous && previous.parentMenu === parent && previous.parentIndex === index) {
            if (keyboard) { previous.selectFirst(); previous.grabFocus(); }
            return;
        }
        trimAfter(parent);
        const dbus = parent.source !== null;
        const child = nodeFactory.createObject(null, {
            isRoot: false, rootNode: node, nodeFactory: nodeFactory,
            parentMenu: parent, parentIndex: index, screen: parent.screen,
            keyboardDriven: !!keyboard, entries: dbus ? [] : entry.children,
            source: dbus ? entry : null
        });
        if (!child) return;
        liveNodes = liveNodes.concat([child]);
        child.present();
        if (keyboard) child.selectFirst();
    }
    function backOne() {
        if (!liveNodes.length) return;
        const tip = tipNode();
        const parent = tip.parentMenu;
        trimAfter(parent);
        parent.grabFocus();
    }
    function closeCascade(cancelled) {
        if (!isRoot) { rootNode.closeCascade(cancelled); return; }
        if (closing) return;
        closing = true;
        cancelSpawn();
        visible = false;
        trimAfter(node);
        currentIndex = -1;
        if (cancelled && cancelHandler) cancelHandler();
        finished();
    }
    function activateIndex(index, keyboard) {
        cancelSpawn();
        const entry = entryAt(index);
        if (!entry || !entry.enabled || entry.isSeparator) return;
        if (entry.hasChildren) rootNode.spawnNode(node, index, entry, keyboard);
        else {
            const handler = rootNode.leafHandler;
            // Hide before dispatch: actions may synchronously disconnect or open a new menu.
            rootNode.closeCascade(false);
            if (handler) handler(entry);
        }
    }
    function activateHighlighted() { activateIndex(currentIndex, true); }
    function _key(event) {
        const tip = tipNode();
        if (event.key === Qt.Key_Escape) closeCascade(true);
        else if (event.key === Qt.Key_Left) backOne();
        else if (event.key === Qt.Key_Right) {
            const entry = tip.entryAt(tip.currentIndex);
            if (entry && entry.hasChildren) tip.activateHighlighted();
        } else if (event.key === Qt.Key_Down) tip.moveHighlight(1);
        else if (event.key === Qt.Key_Up) tip.moveHighlight(-1);
        else if (event.key === Qt.Key_Home) { tip.currentIndex = -1; tip.moveHighlight(1); }
        else if (event.key === Qt.Key_End) { tip.currentIndex = 0; tip.moveHighlight(-1); }
        else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space)
            tip.activateHighlighted();
        else if (event.text && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)))
            tip.typeAhead(event.text);
        else return;
        event.accepted = true;
    }
}
