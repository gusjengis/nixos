// Effects require RHI, not Qt Quick's software scene graph:
// QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=rhi QSG_RHI_BACKEND=opengl LIBGL_ALWAYS_SOFTWARE=1 qmltestrunner -input test_dock_highlight.qml
import QtQuick
import QtTest
import "config" as Desktop

Item {
    width: 100
    height: 100
    Desktop.DockTile {
        id: tile
        centerX: 50
        centerY: 43.5
        // Transparent margins plus saturated, midtone, white and black ink.
        source: "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="59" height="59"><path fill="#ff8040" d="M5 5h25v49H5z"/><path fill="#808080" d="M30 5h24v25H30z"/><path fill="white" d="M30 30h12v24H30z"/><path fill="black" d="M42 30h12v24H42z"/></svg>')
    }
    TestCase {
        name: "DockHighlight"
        when: windowShown
        function test_render() {
            tryVerify(() => tile.children[0].status === Image.Ready);
            waitForRendering(tile);
            const normal = grabImage(tile);
            tile.held = true;
            waitForRendering(tile);
            const held = grabImage(tile);
            for (const point of [[20, 30], [45, 30], [40, 55], [50, 55]]) {
                const x = point[0], y = point[1];
                for (const channel of ["red", "green", "blue"])
                    verify(Math.abs(held[channel](x, y) - normal[channel](x, y) * 0.7) <= 2,
                           channel + " must darken proportionally at " + x + "," + y
                           + ": " + normal[channel](x, y) + " -> " + held[channel](x, y));
            }
            for (let y = 0; y < normal.height; y++)
                for (let x = 0; x < normal.width; x++) {
                    compare(held.alpha(x, y), normal.alpha(x, y), "Highlight must preserve alpha and geometry");
                    if (x < 10 || x >= 63 || y < 17 || y >= 70)
                        compare(held.pixel(x, y), normal.pixel(x, y), "No highlight outside icon artwork");
                }
            tile.held = false;
            waitForRendering(tile);
            verify(grabImage(tile).equals(normal), "Closing menu must restore original icon");
            mousePress(tile, 36, 40, Qt.LeftButton);
            verify(tile.darkened);
            waitForRendering(tile);
            verify(grabImage(tile).equals(held), "Press and menu use identical highlight");
            mouseRelease(tile, 36, 40, Qt.LeftButton);
            verify(!tile.darkened);
            waitForRendering(tile);
            verify(grabImage(tile).equals(normal), "Release restores original icon");
        }
    }
}
