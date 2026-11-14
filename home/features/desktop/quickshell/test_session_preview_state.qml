import QtQuick
import Quickshell
import "config" as Desktop
import "config/SessionOverview.js" as Overview

ShellRoot {
    id: test
    property var session: ({ name: "Layered", windows: ["normal", "special"],
        workspaces: { "DP-1": ["normal", "empty"] }, slots: { "DP-1": 1 },
        specials: { terminal: "special:terminal" }, visible_specials: { "DP-1": "terminal" } })
    QtObject {
        id: model
        function overview(session) {
            return Overview.overview(session, [
                { address: "normal", mapped: true, workspace: { address: "normal" }, monitor: 0,
                    focusHistoryID: 1, at: [100, 50], size: [1920, 1080] },
                { address: "special", mapped: true, workspace: { address: "special:terminal" }, monitor: 0,
                    focusHistoryID: 0, at: [200, 150], size: [800, 600] }
            ], [{ id: 0, name: "DP-1", x: 100, y: 50, width: 1920, height: 1080, scale: 1 }]);
        }
        function apps(windows) { return []; }
    }
    Desktop.SessionCard {
        id: card
        width: 426; height: 342
        session: test.session
        overviewModel: model
        previewsEnabled: true
    }
    function collect(item, name) {
        let result = item.objectName === name ? [item] : [];
        for (const child of item.children || []) result = result.concat(collect(child, name));
        return result;
    }
    function check(value, message) {
        if (!value) throw new Error(message);
    }
    Timer {
        running: true; repeat: true; interval: 200
        property int stage: 0
        onTriggered: {
            try {
                const background = collect(card, "session-preview-background")[0];
                const windows = collect(card, "session-preview-window");
                if (stage === 0) {
                    check(card.workspace.name === "special:terminal", "Visible special selected");
                    check(windows.length === 2, "Capture both normal and special windows");
                    check(collect(background, "session-preview-window")[0].modelData.address === "normal", "Fullscreen app behind special");
                    check(background.layer.enabled, "Blur applied to background only");
                    check(windows.find(window => window.modelData.address === "special").parent !== background, "Special stays sharp");
                    card.previewKey = "special:terminal:0";
                    test.session = Object.assign({}, test.session, { slots: { "DP-1": 2 }, visible_specials: {} });
                } else if (stage === 1) {
                    check(card.previewKey === "", "Workspace change clears hover override");
                    check(card.workspace.name === "empty" && windows.length === 0, "Empty desktop replaces last focused special");
                    check(!background.layer.enabled, "Normal workspace has no special blur");
                    test.session = Object.assign({}, test.session, { slots: { "DP-1": 1 } });
                } else if (stage === 2) {
                    check(card.workspace.name === "normal" && windows.length === 1, "Normal workspace refreshes without focus change");
                    test.session = Object.assign({}, test.session, { visible_specials: { "DP-1": "terminal" } });
                } else {
                    check(card.workspace.special && windows.length === 2 && background.layer.enabled, "Reopened special restores layered blurred view");
                    console.log("PASS: reactive workspace changes, empty desktop, layered captures and background-only blur");
                    Qt.quit();
                }
                stage++;
            } catch (error) {
                console.error("FAILED:", error);
                Qt.exit(1);
            }
        }
    }
}
