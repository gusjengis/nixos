import QtQuick
import Quickshell
import "config" as Desktop

ShellRoot {
    id: root
    property int stage: 0
    property string first: Quickshell.env("TEST_DESKTOP_FIRST")
    property string second: Quickshell.env("TEST_DESKTOP_SECOND")
    Desktop.DesktopFilesModel { id: files; directory: root.first }
    function check(value, message) { if (!value) throw new Error(message); }
    Timer {
        interval: 50; running: true; repeat: true
        onTriggered: {
            try {
                if (!files.loaded || files.busy) return;
                root.check(!files.error, files.error);
                if (root.stage === 0) {
                    root.check(files.entries.length === 1 && files.entries[0].name === "first.txt", "Read context home, exclude metadata");
                    files.directory = root.second;
                    root.check(!files.loaded && !files.entries.length, "Clear old icons immediately");
                    root.stage = 1;
                } else if (root.stage === 1) {
                    root.check(files.entries.length === 0, "Empty context must stay empty");
                    files.directory = root.first;
                    files.directory = root.second;
                    root.stage = 2;
                } else if (root.stage === 2) {
                    root.check(files.entries.length === 0, "Reject late previous-context listing");
                    files.run("new-folder", []);
                    root.stage = 3;
                } else if (root.stage === 3) {
                    if (files.entries.length === 0) { files.refresh(); return; }
                    root.check(files.entries.length === 1 && files.entries[0].name === "untitled folder", "Create in originating desktop folder");
                    files.directory = "";
                    root.check(!files.loaded && !files.entries.length, "No owner clears desktop");
                    console.log("PASS: desktop model listing, context switch, stale response, new folder, no owner");
                    Qt.quit();
                }
            } catch (error) { console.error("FAILED:", error); Qt.quit(); }
        }
    }
    Timer {
        interval: 10000; running: true
        onTriggered: { console.error("FAILED: desktop model timeout"); Qt.quit(); }
    }
}
