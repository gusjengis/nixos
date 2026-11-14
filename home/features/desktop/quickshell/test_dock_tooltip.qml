import QtQuick
import Quickshell
import "config" as Desktop

ShellRoot {
    QtObject { id: first }
    QtObject { id: second }
    Desktop.DockTooltip { id: tip }
    Item { Desktop.DockTile { source: "" } }

    function check(value, message) {
        if (!value) throw new Error(message);
    }
    Timer {
        interval: 100; running: true
        onTriggered: {
            try {
                tip.setHovered(first, "Editor", true, 400);
                check(tip.shown && tip.centerX === 400 && tip.text === "Editor", "Entering icon shows its label");
                tip.setHovered(first, "Editor", false, 400);
                check(!tip.shown, "Gap between icons hides label immediately");
                tip.setHovered(second, "Editor", true, 473);
                tip.setHovered(first, "Editor", false, 400);
                check(tip.shown && tip.centerX === 473, "Late exit from identically named app must not hide new label");
                tip.setHovered(second, "Editor", false, 473);
                check(!tip.shown && tip.hoveredItem === null, "Exit clears label ownership");
                check(tip.implicitHeight === tip.bodyHeight + tip.pointerHeight + 2*tip.pad, "Compositor silhouette includes pointer");
                check(tip.margins.bottom === tip.dockBottom + 2 - tip.pad, "Pointer ends 2 px above dock");
                // CoreText 14 pt system-font advances measured on macOS 27:
                // 100.885, 35.718, 40.667, 66.445, 105.0, 28.082 px.
                const labels = [["Google Chrome",127],["Trash",62],["Finder",67],
                                ["Chromium",93],["System Settings",131],["kitty",55]];
                for (const [name, width] of labels) {
                    tip.text = name;
                    check(Math.abs(tip.bodyWidth - width) <= 1, "Mac measured label width: " + name);
                }
                console.log("PASS: dock tooltip enter, gap, duplicate-name event ordering, exit, silhouette and placement");
            } catch (error) {
                console.error("FAILED:", error.message);
            }
            Qt.quit();
        }
    }
}
