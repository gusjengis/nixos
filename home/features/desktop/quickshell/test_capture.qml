import QtQuick
import Quickshell
import Quickshell.Io
import "config"

Scope {
    id: test
    Capture { id: capture }
    property var field
    property string expected: Quickshell.env("TEST_CAPTURE_BODY") || "Native dictation capture acceptance."
    property bool pasted: false

    function textField(item) {
        if (String(item).startsWith("TextArea")) return item;
        for (const child of item.children || []) {
            const found = textField(child);
            if (found) return found;
        }
        return null;
    }

    Component.onCompleted: {
        field = textField(capture.contentItem);
        if (!field) {
            console.error("FAILED: missing dictation field");
            Qt.quit();
            return;
        }
        capture.contextId = Quickshell.env("TEST_CAPTURE_CONTEXT");
        capture.visible = true;
        field.forceActiveFocus();
        capture.released();
        clipboard.running = true;
    }

    Process {
        id: clipboard
        command: ["wl-copy", "--", test.expected]
        onExited: (code, status) => {
            if (code !== 0 || status !== 0) {
                console.error("FAILED: clipboard write");
                Qt.quit();
            } else {
                pasteDelay.start();
            }
        }
    }

    Timer {
        id: pasteDelay
        interval: 100
        onTriggered: paste.running = true
    }

    Process {
        id: paste
        // Same native key combination Handy sends for shift_insert.
        command: ["wtype", "-M", "shift", "-k", "Insert"]
        onExited: (code, status) => {
            if (code !== 0 || status !== 0) {
                console.error("FAILED: paste key");
                Qt.quit();
            }
        }
    }

    Timer {
        interval: 50
        running: true
        repeat: true
        onTriggered: {
            if (test.field && test.field.text === test.expected)
                test.pasted = true;
            if (capture.phase === "saved") {
                if (!test.pasted) {
                    let index = 0;
                    while (index < test.expected.length && test.field.text[index] === test.expected[index]) index++;
                    console.error("FAILED: pasted transcript differs at " + index
                        + " (received " + test.field.text.length + ", expected " + test.expected.length + ")");
                }
                else
                    console.log("PASS: native dictation writer and whole-text paste");
                Qt.quit();
            } else if (capture.phase === "failed") {
                console.error("FAILED: " + capture.errorText);
                Qt.quit();
            }
        }
    }
    Timer {
        interval: 10000
        running: true
        onTriggered: { console.error("FAILED: dictation timeout"); Qt.quit(); }
    }
}
