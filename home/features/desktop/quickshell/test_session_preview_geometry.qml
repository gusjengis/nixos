import QtQuick
import Quickshell
import "config" as Desktop

ShellRoot {
    id: test
    property var workspace: ({
        width: 3840, height: 2160, x: 100, y: 50, monitorId: 0,
        windows: [{ at: [100, 50], size: [3840, 2160] }]
    })
    QtObject {
        id: model
        function overview(session) { return { groups: [test.workspace], windows: [] }; }
        function apps(windows) { return []; }
    }
    Desktop.SessionCard {
        id: card
        width: 426; height: 342
        session: ({ name: "Fullscreen", window_count: 1 })
        overviewModel: model
        previewsEnabled: true
    }
    // A deliberately wrong-shaped caller must not paint wallpaper outside its
    // monitor canvas, even independently of the correctly sized gallery card.
    Desktop.SessionPreview {
        id: stretched
        width: 800; height: 200
        workspace: test.workspace
    }
    function find(item, name) {
        if (item.objectName === name) return item;
        for (const child of item.children || []) {
            const found = find(child, name);
            if (found) return found;
        }
        return null;
    }
    function near(actual, expected, message) {
        if (!Number.isFinite(actual) || !Number.isFinite(expected) || Math.abs(actual - expected) > 0.01)
            throw new Error(message + ": " + actual + " != " + expected);
    }
    function verify(item) {
        const desktop = find(item, "session-preview-desktop");
        const wallpaper = find(item, "session-preview-wallpaper");
        const window = find(item, "session-preview-window");
        near(desktop.width / desktop.height, test.workspace.width / test.workspace.height, "Monitor aspect");
        near(wallpaper.width, desktop.width, "Wallpaper width matches canvas");
        near(wallpaper.height, desktop.height, "Wallpaper height matches canvas");
        near(window.x, 0, "Fullscreen window starts at left edge");
        near(window.y, 0, "Fullscreen window starts at top edge");
        near(window.width, wallpaper.width, "Fullscreen window covers wallpaper width");
        near(window.height, wallpaper.height, "Fullscreen window covers wallpaper height");
    }
    Timer {
        running: true
        repeat: true
        interval: 200
        property int stage: 0
        onTriggered: {
            try {
                const viewport = find(card, "session-card-preview");
                near(viewport.width / viewport.height, test.workspace.width / test.workspace.height, "Card preview aspect");
                verify(card);
                verify(stretched);
                if (stage++ === 0) {
                    test.workspace = { width: 1080, height: 1920, x: -1080, y: 0, monitorId: 1,
                        windows: [{ at: [-1080, 0], size: [1080, 1920] }] };
                } else {
                    console.log("PASS: 16:9 and portrait preview aspects, fullscreen coverage, wallpaper bounds and monitor offsets");
                    Qt.quit();
                }
            } catch (error) {
                console.error("FAILED:", error);
                Qt.exit(1);
            }
        }
    }
}
