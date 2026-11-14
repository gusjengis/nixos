import QtQuick
import Quickshell
import Quickshell.Io
import "config" as Desktop
import "config/state" as State
import "config/theme" as Style

// Run only inside a visible disposable nested compositor, with SESSION_GALLERY_TEST=1.
// Own fixture windows provide real capture sources; no desktop session actions
// are executed. Proves QML model conversion, composition and captured pixels.
ShellRoot {
    property int stage: 0
    property int attempts: 0
    Desktop.SessionOverviewModel { id: overview }
    Desktop.SessionPicker { id: picker }
    Process {
        id: fixtures
        command: ["qs", "--no-color", "-p", Quickshell.shellDir + "/test_session_gallery_windows.qml"]
        running: Quickshell.env("SESSION_GALLERY_TEST") === "1"
        stdout: StdioCollector { onStreamFinished: if (text) console.log("Fixture stdout:", text) }
        onExited: (code, status) => console.log("Fixture exit", code, status)
        stderr: StdioCollector { onStreamFinished: if (text) console.log("Fixture stderr:", text) }
    }
    function collect(item, name) {
        let result = item.objectName === name ? [item] : [];
        for (const child of item.children || [])
            result = result.concat(collect(child, name));
        return result;
    }
    function check(value, message) {
        if (!value) throw new Error(message);
    }
    Timer {
        running: true
        repeat: true
        interval: 800
        onTriggered: {
            try {
                check(Quickshell.env("SESSION_GALLERY_TEST") === "1", "Requires disposable compositor");
                if (stage === 0) {
                    const windows = overview.windows.filter(window => (window.title || "").startsWith("Gallery fixture"));
                    if (windows.length !== 2 && ++attempts < 10)
                        return;
                    if (windows.length !== 2)
                        console.log("Fixture discovery", fixtures.running, fixtures.command, JSON.stringify(overview.windows.map(window => ({ title: window.title, address: window.address }))));
                    check(windows.length === 2, "Both fixture windows discovered");
                    State.DesktopSessions.contextCatalog = { contexts: [], nodes: [] };
                    State.DesktopSessions.snapshot = { active: "fixture-0", previous: "fixture-1", sessions: windows.map((window, index) => ({
                        id: "fixture-" + index, name: index === 0 ? "Test/Blue" : "Test/Green",
                        windows: [window.address], window_count: 1,
                        specials: {}, workspaces: {}
                    })) };
                    State.FocusGuard.suspended = true;
                    picker.open(false);
                    stage = 1;
                    attempts = 0;
                    return;
                }
                const gallery = collect(picker.contentItem, "session-gallery")[0];
                check(gallery && gallery.count === 2, "Gallery shows both sessions");
                check(gallery.currentItem.overview.groups.length === 1, "QML delegate retains window ownership");
                const captures = collect(picker.contentItem, "session-window-capture");
                if (++attempts < 10 && (captures.length !== 2 || !captures.every(capture => capture.hasContent)))
                    return;
                check(captures.length === 2 && captures.every(capture => capture.hasContent), "Both sessions have actual captured pixels");
                Style.Theme.glassActive = false;
                const panel = collect(picker.contentItem, "session-picker-body")[0];
                panel.grabToImage(result => {
                    result.saveToFile("/tmp/opencode/session-gallery-fixture.png");
                    console.log("PASS: rendered two-column gallery with real per-session window captures");
                    fixtures.running = false;
                    Qt.quit();
                });
                stop();
            } catch (error) {
                console.error("FAILED:", error);
                Qt.exit(1);
            }
        }
    }
}
