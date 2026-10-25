import QtQuick
import Quickshell
import "config" as Desktop

// Run with isolated CONTEXT_ROOT and fixture UUIDs; no desktop mutations.
ShellRoot {
    id: root
    property int stage: 0
    Desktop.InProgressModel {
        id: notebook
        contextId: Quickshell.env("TEST_CONTEXT_FIRST")
    }

    function check(condition, message) {
        if (!condition) throw new Error(message);
    }

    Timer {
        interval: 50
        repeat: true
        running: true
        onTriggered: {
            try {
                if (!notebook.loaded || notebook.busy) return;
                check(!notebook.error, notebook.error);
                if (root.stage === 0) {
                    check(notebook.cards.length === 91, "Must collect every paginated In-Progress and Todo card");
                    check(notebook.cards.slice(0, 90).every(card => card.status === "In-Progress"), "In-Progress must come first");
                    check(notebook.cards[90].status === "Todo", "Todo must follow In-Progress");
                    root.stage = 1;
                    notebook.contextId = Quickshell.env("TEST_CONTEXT_SECOND");
                    check(notebook.cards.length === 0 && !notebook.loaded, "Switch must clear previous cards immediately");
                } else if (root.stage === 1) {
                    check(notebook.cards.length === 0, "Empty context must not inherit another notebook");
                    root.stage = 2;
                    notebook.contextId = Quickshell.env("TEST_CONTEXT_FIRST");
                    // Switch while request is still in flight; its reply must be discarded.
                    notebook.contextId = Quickshell.env("TEST_CONTEXT_SECOND");
                } else if (root.stage === 2) {
                    check(notebook.cards.length === 0, "Late response must not leak cards across contexts");
                    root.stage = 3;
                    notebook.contextId = "";
                    check(!notebook.loaded && !notebook.cards.length, "No saved context must clear model");
                    notebook.contextId = Quickshell.env("TEST_CONTEXT_FIRST");
                } else {
                    check(notebook.cards.length === 91, "Must recover after rapid switching and no owner");
                    console.log("PASS: In-Progress filtering, pagination, empty state, context switching, stale-response isolation");
                    Qt.quit();
                }
            } catch (error) {
                console.error("FAILED:", error);
                Qt.quit();
            }
        }
    }
    Timer {
        interval: 15000
        running: true
        onTriggered: { console.error("FAILED: notebook model timed out"); Qt.quit(); }
    }
}
