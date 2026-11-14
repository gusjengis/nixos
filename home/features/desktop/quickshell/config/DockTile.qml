import QtQuick
import QtQuick.Effects

// One Dock slot: icon centred at (centerX, centerY), running dot below.
Item {
    id: tile

    property real centerX: 0
    property real centerY: 0
    property int iconSize: 59
    property real dpr: 1
    property string source: ""
    property bool running: false
    readonly property bool hovered: labelHover.hovered
    // macOS keeps the icon darkened while its Dock menu is open.
    property bool held: false
    property bool movable: false
    property bool dragging: false
    readonly property bool darkened: mouse.pressed || held
    signal activated()
    signal menuRequested()
    signal dragMoved(real pointerX)
    signal dragFinished(bool canceled)

    x: centerX - 36.5
    y: 0
    width: 73
    height: parent ? parent.height : 89

    Image {
        id: icon
        x: Math.round(tile.width / 2 - tile.iconSize / 2)
        y: Math.round(tile.centerY - tile.iconSize / 2)
        width: tile.iconSize
        height: tile.iconSize
        source: tile.source
        sourceSize: Qt.size(Math.ceil(tile.iconSize * tile.dpr), Math.ceil(tile.iconSize * tile.dpr))
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
        asynchronous: true
        visible: !tile.darkened
    }
    // Tint toward black without subtracting/clipping darker color channels.
    // Keep alpha untouched, including antialiased edges and icon shadows.
    MultiEffect {
        source: icon
        anchors.fill: icon
        visible: tile.darkened
        colorization: 0.3
        colorizationColor: "black"
    }

    // Running indicator: 4 px dot, additive +124 (encoded gray 124 ink).
    Rectangle {
        visible: tile.running
        x: Math.floor(tile.width / 2) - 2
        y: 81
        width: 4
        height: 4
        radius: 2
        color: "#7c7c7c"
    }

    // The click target remains the whole slot. Labels belong to the icon:
    // crossing the 14 px gap must hide them, rather than carry them across.
    Item {
        x: Math.round(tile.width / 2 - tile.iconSize / 2)
        y: Math.round(tile.centerY - tile.iconSize / 2)
        width: tile.iconSize
        height: tile.iconSize
        HoverHandler { id: labelHover }
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        // The Dock opens its menu on secondary press, not release.
        property real pressX: 0
        property real pressY: 0
        property real pressOffset: 0
        property bool wasDrag: false
        preventStealing: true
        onPressed: mouse => {
            wasDrag = false;
            const point = mapToItem(tile.parent, mouse.x, mouse.y);
            pressX = point.x;
            pressY = point.y;
            pressOffset = point.x - tile.centerX;
            if (mouse.button === Qt.RightButton) tile.menuRequested();
        }
        onPositionChanged: mouse => {
            if (!(pressedButtons & Qt.LeftButton) || !tile.movable) return;
            const point = mapToItem(tile.parent, mouse.x, mouse.y);
            if (!tile.dragging && Math.hypot(point.x - pressX, point.y - pressY) < 8) return;
            wasDrag = true;
            tile.dragging = true;
            tile.dragMoved(point.x - pressOffset);
        }
        onReleased: mouse => {
            if (tile.dragging) {
                tile.dragging = false;
                tile.dragFinished(false);
            }
        }
        onCanceled: {
            if (tile.dragging) {
                tile.dragging = false;
                tile.dragFinished(true);
            }
        }
        onClicked: mouse => { if (mouse.button === Qt.LeftButton && !wasDrag) tile.activated(); }
    }
}
