import QtQuick
import Quickshell
import Quickshell.Io
import "config/bar/components" as UI
import "config/theme"

ShellRoot {
    id: root
    property int stage: 0
    property string focused: ""
    readonly property string captureDirectory: Quickshell.env("TEST_CAPTURE_DIR")
    function check(value, message) { if (!value) throw new Error(message); }
    QtObject {
        id: model
        property var sessions: [{pane: "%0"}, {pane: "%1"}]
        property int selected: -1
        property int offset: 0
        property int pageSize: 2
        property int cellHeight: Number(Quickshell.env("TEST_CELL_HEIGHT"))
        property int bitmapWidth: Number(Quickshell.env("TEST_BITMAP_WIDTH"))
        property int bitmapHeight: Number(Quickshell.env("TEST_BITMAP_HEIGHT"))
        property string bitmapPath: Quickshell.env("TEST_BITMAP_PATH")
        property int bitmapGeneration: Number(Quickshell.env("TEST_BITMAP_GENERATION") || "0")
        function showPanel(panel) {}
        function hidePanel(panel) {}
        function moveSelection(steps) { selected = Math.max(0, Math.min(1, selected + steps)); }
        function scroll(steps) {}
        function focus(pane) { root.focused = pane; }
    }
    PanelWindow {
        screen: Quickshell.screens[0]
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        anchors { top: true; right: true }
        implicitWidth: 600
        implicitHeight: 30
        mask: Region { width: 0; height: 0 }
        Item { id: anchor; x: 568; width: 32; height: 22 }
    }
    UI.OpenCodePopup { id: popup; service: model }
    Timer {
        interval: 10
        repeat: true
        running: true
        onTriggered: {
            try {
                if (!popup.contentReady) return;
                if (root.stage === 0) {
                    popup.toggle(anchor);
                    root.stage = 1;
                    return;
                }
                if (root.stage !== 1 || popup.firstPaintMs < 0) return;
                check(popup.visible, "Popup must remain open");
                check(popup.firstPaintMs < 100, "Cached first paint took " + popup.firstPaintMs + "ms");
                check(popup.borderSize === 2, "Window border must be two pixels");
                check(popup.popupRadius === Theme.windowRadius, "Popup must inherit Hyprland rounding");
                check(popup.popupWidth === model.bitmapWidth + 4, "Border must not rescale cell pixels");
                check(popup.sessionAt(3 * model.cellHeight - 1) === -1, "Header is not a session");
                check(popup.sessionAt(3 * model.cellHeight) === 0, "First cell row maps first session");
                check(popup.sessionAt(7 * model.cellHeight) === 1, "Second cell row maps second session");
                check(popup.sessionAt(11 * model.cellHeight) === -1, "Bottom padding is not a session");
                popup.handleKey(Qt.Key_Down);
                popup.handleKey(Qt.Key_Down);
                popup.handleKey(Qt.Key_Return);
                check(root.focused === "%1" && !popup.visible, "Keyboard activation must focus selected chat and close");
                popup.toggle(anchor);
                popup.activate(popup.sessionAt(3 * model.cellHeight));
                check(root.focused === "%0" && !popup.visible, "Pointer cell activation must focus exact chat and close");
                popup.toggle(anchor);
                popup.handleKey(Qt.Key_Escape);
                check(!popup.visible && root.focused === "%0", "Escape must close without activating");
                console.log("PASS: cached first paint, rounded 2px border, cell hits, keyboard/pointer activation, Escape");
                root.stage = 2;
                if (root.captureDirectory) {
                    popup.toggle(anchor);
                    capture.restart();
                } else Qt.quit();
            } catch (error) { console.error("FAILED:", error); Qt.quit(); }
        }
    }
    IpcHandler {
        target: "frameTest"
        function advance(generation: int): void {
            model.bitmapGeneration = generation;
            root.stage++;
            capture.restart();
        }
    }
    Timer {
        id: capture
        interval: 80
        onTriggered: popup.body.grabToImage(result => {
            const index = root.stage - 2;
            if (!result.saveToFile(root.captureDirectory + "/frame-" + index + ".png")) {
                console.error("FAILED: could not capture displayed popup");
                Qt.quit();
                return;
            }
            console.log("FRAME_CAPTURED:" + index);
            if (index === 2) Qt.quit();
        })
    }
    Timer {
        interval: root.captureDirectory ? 10000 : 5000
        running: true
        onTriggered: { console.error("FAILED: popup fixture timed out"); Qt.quit(); }
    }
}
