import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import "state"
import "theme"
import "widgets"

// Dictation capture (CTRL + dictation key). Handy has no way to hand a
// transcript to a caller; it pastes it into whatever has keyboard focus. This
// popup is that focus target: it opens as recording starts, Handy pastes the
// transcript into it after the key is released, and the text is written into
// the originating saved context's notebook.
PanelWindow {
    id: capture

    // "listening" until the key is released, then "transcribing" until text
    // stops arriving, then "saving" / "saved" / "failed".
    property string phase: "listening"
    property string errorText: ""
    property string contextId: ""
    property bool savePending: false

    visible: false
    focusable: true
    exclusionMode: ExclusionMode.Ignore
    anchors.top: true
    margins.top: Math.round(screen.height * 0.2)
    implicitWidth: Math.min(560, screen.width * 0.8)
    implicitHeight: 320
    color: "transparent"
    mask: Region { item: card }
    WlrLayershell.namespace: "quickshell-capture"

    function open() {
        if (owner.running || writer.running)
            return;
        if (visible && phase !== "saved" && phase !== "failed")
            return;
        contextId = "";
        savePending = false;
        owner.running = true;
        closeTimer.stop();
        field.text = "";
        errorText = "";
        phase = "listening";
        visible = true;
        field.forceActiveFocus();
    }

    // Recording stopped; Handy is about to transcribe and paste.
    function released() {
        if (!visible || phase !== "listening")
            return;
        phase = "transcribing";
        if (field.text.trim() === "")
            noTextTimeout.restart();
        else
            quietTimer.restart();
    }

    function cancel() {
        if (!visible)
            return;
        if (phase === "listening")
            Quickshell.execDetached(["handy", "--cancel"]);
        close();
    }

    function close() {
        quietTimer.stop();
        noTextTimeout.stop();
        closeTimer.stop();
        visible = false;
    }

    function save() {
        quietTimer.stop();
        noTextTimeout.stop();
        if (owner.running) {
            savePending = true;
            return;
        }
        const text = field.text.trim();
        if (text === "") {
            close();
            return;
        }
        phase = "saving";
        if (contextId === "") {
            close();
            return;
        }
        writer.command = ["context-notes", "--context", contextId, "capture"];
        writer.captureBody = JSON.stringify({body: text});
        writer.running = true;
    }

    Process {
        id: owner
        command: ["context-notes", "capture-owner"]
        stdout: StdioCollector { id: ownerOutput }
        onExited: (code, status) => {
            if (code === 0 && status === 0) {
                try { capture.contextId = JSON.parse(ownerOutput.text).context_id || ""; }
                catch (_) { capture.contextId = ""; }
            }
            if (capture.savePending && capture.visible) {
                capture.savePending = false;
                capture.save();
            }
        }
    }

    Process {
        id: writer
        property string captureBody: ""
        stdinEnabled: true
        onStarted: {
            write(captureBody);
            stdinEnabled = false;
        }
        onRunningChanged: if (!running) stdinEnabled = true;
        stderr: StdioCollector { id: writerErrors }
        onExited: (code, status) => {
            if (code === 0 && status === 0) {
                capture.phase = "saved";
                closeTimer.interval = 450;
            } else {
                capture.phase = "failed";
                capture.errorText = writerErrors.text.trim() || "context-notes exited with " + code;
                closeTimer.interval = 6000;
            }
            closeTimer.restart();
        }
    }

    // Allow the clipboard paste (or a manual edit) to settle before saving.
    Timer {
        id: quietTimer
        interval: 700
        onTriggered: capture.save()
    }

    // Released but nothing arrived (silence, or transcription failed).
    Timer {
        id: noTextTimeout
        interval: 20000
        onTriggered: capture.close()
    }

    Timer {
        id: closeTimer
        onTriggered: capture.close()
    }

    HyprlandFocusGrab {
        id: focusGrab
        windows: [capture]
        // Clicking away keeps whatever was already transcribed.
        onCleared: {
            if (FocusGuard.suspended)
                return;
            if (capture.phase === "transcribing" && field.text.trim() !== "")
                capture.save();
            else if (capture.phase !== "saving")
                capture.cancel();
        }
    }

    Binding {
        target: focusGrab
        property: "active"
        value: capture.visible && !FocusGuard.suspended
    }

    Rectangle {
        id: card
        width: parent.width
        height: Math.min(parent.height, content.implicitHeight + 36)
        radius: 22
        color: Theme.background
        border { width: 1; color: Qt.rgba(1, 1, 1, 0.14) }

        ColumnLayout {
            id: content
            anchors { fill: parent; margins: 18 }
            spacing: 10

            RowLayout {
                spacing: 10

                SFSymbol {
                    id: micIcon
                    symbol: capture.phase === "saved" ? "checkmark" : capture.phase === "failed" ? "xmark" : "mic.fill"
                    size: 18
                    color: capture.phase === "failed" ? Theme.danger : capture.phase === "listening" ? Theme.accent : Theme.muted

                    SequentialAnimation on opacity {
                        running: capture.visible && capture.phase === "listening"
                        loops: Animation.Infinite
                        onRunningChanged: if (!running) micIcon.opacity = 1
                        NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutQuad }
                        NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutQuad }
                    }
                }

                Text {
                    Layout.fillWidth: true
                    text: ({
                            "listening": "Listening…",
                            "transcribing": "Transcribing…",
                            "saving": "Saving…",
                            "saved": "Saved to notebook",
                            "failed": "Could not save"
                        })[capture.phase]
                    color: capture.phase === "failed" ? Theme.danger : Theme.text
                    font { family: Theme.fontFamily; pixelSize: 16; weight: Font.DemiBold }
                }

                Text {
                    text: "Esc to discard"
                    visible: capture.phase === "listening" || capture.phase === "transcribing"
                    color: Theme.muted
                    font { family: Theme.fontFamily; pixelSize: 12 }
                }
            }

            TextArea {
                id: field
                Layout.fillWidth: true
                Layout.maximumHeight: 230
                // Stays visible even while empty: a hidden item cannot hold
                // the keyboard focus Handy pastes into.
                wrapMode: TextEdit.Wrap
                color: Theme.text
                selectionColor: "#0a84ff"
                selectedTextColor: "#ffffff"
                padding: 0
                background: null
                font { family: Theme.fontFamily; pixelSize: 15 }
                onTextChanged: {
                    if (capture.phase === "transcribing" && text.trim() !== "") {
                        noTextTimeout.stop();
                        quietTimer.restart();
                    }
                }
                Keys.onEscapePressed: capture.cancel()
            }

            Text {
                Layout.fillWidth: true
                visible: capture.errorText !== ""
                text: capture.errorText
                wrapMode: Text.Wrap
                color: Theme.danger
                font { family: Theme.fontFamily; pixelSize: 12 }
            }
        }
    }
}
