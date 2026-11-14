import QtQuick
import QtTest
import "config" as Desktop

Item {
    width: 500
    height: 100
    Desktop.DockTile {
        id: tile
        centerX: 100
        movable: true
        property int clicks: 0
        property int moves: 0
        property int finishes: 0
        property int menus: 0
        onActivated: clicks++
        onMenuRequested: menus++
        onDragMoved: pointerX => { moves++; centerX = pointerX; }
        onDragFinished: canceled => { if (!canceled) finishes++; }
    }
    TestCase {
        name: "DockTileDrag"
        when: windowShown
        function test_pointer() {
            mouseClick(tile, 36, 40, Qt.LeftButton);
            compare(tile.clicks, 1);
            mousePress(tile, 36, 40, Qt.LeftButton);
            mouseMove(tile, 39, 40);
            compare(tile.moves, 0, "Click jitter must not drag");
            mouseMove(tile, 100, 40);
            verify(tile.dragging);
            verify(tile.moves > 0);
            mouseRelease(tile, 36, 40, Qt.LeftButton);
            compare(tile.finishes, 1);
            compare(tile.clicks, 1, "Drag release must not activate app");
            verify(!tile.dragging);
            tile.movable = false;
            mousePress(tile, 36, 40, Qt.LeftButton);
            mouseMove(tile, 100, 40);
            verify(!tile.dragging, "Finder/Trash cannot drag");
            mouseRelease(tile, 36, 40, Qt.LeftButton);
            mouseClick(tile, 36, 40, Qt.RightButton);
            compare(tile.menus, 1, "Secondary press retains menu");
            console.log("PASS: tile pointer drag threshold, release, click suppression, fixed tiles, context menu");
        }
    }
}
