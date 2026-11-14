import QtQuick
import QtQuick.Effects
import Qt.labs.folderlistmodel
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import "theme"
import "state"

// macOS 27 Dock (bottom, no magnification, Tile Size 69 pt), measured on the
// Mac's 3840x2160@1x Ref4K display (MacOS Theme/26-dock). Shows the apps of
// the active desktop session, then a separator and the Trash.
//
// The layer surface is the glass body plus Theme.glassShadowPadding on every
// side; hyprglass draws the "quickshell-dock" material (config/glass.lua)
// under it. Running dots and the separator use encoded gray 124 ink, which
// that layer composites additively like macOS's plus-lighter.
PanelWindow {
    id: dock

    required property var modelData
    screen: modelData

    // Measured geometry, logical px.
    readonly property int tile: 73          // icon pitch
    readonly property int sidePadding: 8     // body edge to first tile
    readonly property int separatorGap: 32   // extra width of the separator slot
    readonly property int bodyHeight: 89
    readonly property int bottomGap: 5       // screen bottom to body
    // MacOS-Native icons keep a 15/512 margin; Apple's grid keeps 100/1024.
    // 59 px draws their artwork at the Mac's 55 px body for a 69 pt tile.
    readonly property int iconSize: 59
    readonly property real iconCenterY: 43.5
    readonly property int pad: Theme.glassShadowPadding

    readonly property var apps: model.items
    property string dragKey: ""
    property real dragX: 0
    property int dragIndex: -1
    property var previewOrder: []
    onAppsChanged: cancelDrag()

    function cancelDrag() { dragKey = ""; dragIndex = -1; previewOrder = []; }
    function moveDrag(app, pointerX) {
        if (!dragKey) {
            dockMenu.close();
            previewOrder = apps.map(model.orderKey);
            dragKey = model.orderKey(app);
        }
        dragX = Math.max(tileCenter(apps[0].permanent ? 1 : 0), Math.min(tileCenter(apps.length - 1), pointerX));
        const target = Math.max(apps[0].permanent ? 1 : 0,
            Math.min(apps.length - 1, Math.floor((dragX - sidePadding) / tile)));
        const next = previewOrder.slice();
        next.splice(target, 0, next.splice(next.indexOf(dragKey), 1)[0]);
        previewOrder = next;
        dragIndex = target;
    }
    function finishDrag(canceled) {
        const key = dragKey;
        const target = dragIndex;
        const snapshot = apps;
        cancelDrag();
        // Commit after release delivery: rebuilding a Repeater destroys its
        // delegates, including the MouseArea that still owns this event.
        if (!canceled && key) Qt.callLater(() => {
            if (apps === snapshot) model.reorder(key, target);
        });
    }
    readonly property bool trashFull: trashFiles.count > 0
    readonly property int bodyWidth: 2 * sidePadding + (apps.length + 1) * tile + separatorGap
    readonly property real dpr: screen ? screen.devicePixelRatio : 1

    color: "transparent"
    focusable: false
    WlrLayershell.namespace: "quickshell-dock"
    WlrLayershell.layer: WlrLayer.Top
    anchors.bottom: true
    implicitWidth: bodyWidth + 2 * pad
    implicitHeight: bodyHeight + 2 * pad
    margins.bottom: bottomGap - pad
    // Hyprland reserves exclusiveZone + margin: keep windows above the body,
    // as macOS keeps zoomed windows above the Dock.
    exclusiveZone: bodyHeight + bottomGap - margins.bottom
    mask: Region { item: body }

    DockModel { id: model }

    IpcHandler {
        target: "dock-" + (dock.screen ? dock.screen.name : "unknown")
        function snapshot(): string { return JSON.stringify(dock.apps); }
        // Same path as a secondary press; the last slot is the Trash.
        function openMenu(index: int): void {
            if (index >= 0 && index < dock.apps.length) {
                const tile = appTiles.itemAt(index);
                dockMenu.openApp(tile, dock.apps[index], dock.screenX(tile), dock.menuBottom());
            } else if (index === dock.apps.length)
                dockMenu.openTrash(trash, dock.trashFull, dock.screenX(trash), dock.menuBottom());
        }
    }

    FolderListModel {
        id: trashFiles
        folder: "file://" + Quickshell.env("HOME") + "/.local/share/Trash/files"
        showDirs: true
        showHidden: true
    }

    function tileCenter(index) {
        // Apps fill slots 0..n-1; the Trash follows the separator gap.
        const x = sidePadding + index * tile + tile / 2;
        return index >= apps.length ? x + separatorGap : x;
    }

    Item {
        id: body
        x: dock.pad
        y: dock.pad
        width: dock.bodyWidth
        height: dock.bodyHeight

        // Fallback body when the compositor glass is unavailable.
        Rectangle {
            anchors.fill: parent
            visible: !Theme.glassActive
            radius: 24
            color: "#d0202020"
            border { width: 1; color: Theme.windowBorder }
        }

        Repeater {
            id: appTiles
            model: dock.apps

            delegate: DockTile {
                id: appTile
                required property var modelData
                required property int index
                centerX: dock.dragKey === model.orderKey(modelData) ? dock.dragX
                    : dock.tileCenter(dock.dragKey ? dock.previewOrder.indexOf(model.orderKey(modelData)) : index)
                z: dragging ? 1 : 0
                movable: !modelData.permanent
                onDragMoved: pointerX => dock.moveDrag(modelData, pointerX)
                onDragFinished: canceled => dock.finishDrag(canceled)
                Behavior on centerX {
                    enabled: !!dock.dragKey && !appTile.dragging
                    NumberAnimation { duration: 120; easing.type: Easing.OutCubic }
                }
                centerY: dock.iconCenterY
                iconSize: dock.iconSize
                dpr: dock.dpr
                source: modelData.icon
                running: modelData.running
                held: dockMenu.heldItem === appTile
                onActivated: model.activate(modelData)
                onMenuRequested: dockMenu.openApp(appTile, modelData, dock.screenX(appTile), dock.menuBottom())
                onHoveredChanged: tooltip.track(appTile, modelData.name, hovered)
            }
        }

        // Separator: 1 px, 65 px tall, additive +65 (gray 124 at 52%).
        Rectangle {
            x: dock.sidePadding + dock.apps.length * dock.tile + dock.separatorGap / 2
            y: 12
            width: 1
            height: 65
            color: "#7c7c7c"
            opacity: 65 / 124
        }

        DockTile {
            id: trash
            centerX: dock.tileCenter(dock.apps.length)
            centerY: dock.iconCenterY
            iconSize: dock.iconSize
            dpr: dock.dpr
            source: Quickshell.iconPath(dock.trashFull ? "user-trash-full" : "user-trash", true)
            running: false
            held: dockMenu.heldItem === trash
            onMenuRequested: dockMenu.openTrash(trash, dock.trashFull, dock.screenX(trash), dock.menuBottom())
            // Follow profile updates even when this shell inherited an old store path in PATH.
            onActivated: Quickshell.execDetached([Quickshell.env("HOME") + "/.nix-profile/bin/strata", "trash:///"])
            onHoveredChanged: tooltip.track(trash, "Trash", hovered)
        }
    }

    DockMenu {
        id: dockMenu
        screen: dock.screen
        dockModel: model
    }

    // Measured: the menu body ends 13 pt above the Dock body, with its 10 pt
    // pointer tip at the icon centre.
    function screenX(item) { return mapToGlobalX() + pad + item.centerX; }
    function menuBottom() { return (screen ? screen.height : 0) - bottomGap - bodyHeight - 13; }

    DockTooltip {
        id: tooltip
        screen: dock.screen
        suppressed: dockMenu.open || !!dock.dragKey
        dockBottom: dock.bottomGap + dock.bodyHeight
        function track(item, label, hovered) {
            setHovered(item, label, hovered, dock.mapToGlobalX() + dock.pad + item.centerX);
        }
    }

    // Window x of the body relative to the screen's left edge.
    function mapToGlobalX() {
        return ((screen ? screen.width : 0) - width) / 2;
    }
}
