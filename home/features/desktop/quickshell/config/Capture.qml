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
    readonly property int shadowPadding: Theme.glassShadowPadding
    readonly property color statusColor: phase === "failed" ? "#ff6961"
        : phase === "saved" ? "#30d158" : "#0a84ff"

    visible: false
    focusable: true
    exclusionMode: ExclusionMode.Ignore
    anchors.top: true
    margins.top: Math.round(screen.height * 0.2) - shadowPadding
    implicitWidth: Math.min(480, screen.width * 0.8) + 2 * shadowPadding
    implicitHeight: card.height + 2 * shadowPadding
    color: "transparent"
    mask: Region { item: card; radius: card.radius }
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
        x: capture.shadowPadding
        y: capture.shadowPadding
        width: parent.width - 2 * capture.shadowPadding
        height: content.implicitHeight + 40
        radius: 24
        color: Theme.glassActive ? "transparent" : Theme.background
        border { width: Theme.glassActive ? 0 : 1; color: "#30ffffff" }

        ColumnLayout {
            id: content
            anchors { fill: parent; margins: 20 }
            spacing: 16

            RowLayout {
                spacing: 12

                Rectangle {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 40
                    radius: 20
                    color: Qt.rgba(capture.statusColor.r, capture.statusColor.g, capture.statusColor.b, 0.18)

                    SFSymbol {
                        id: micIcon
                        anchors.centerIn: parent
                        symbol: capture.phase === "saved" ? "checkmark" : capture.phase === "failed" ? "xmark" : "mic.fill"
                        size: 18
                        color: capture.statusColor

                        SequentialAnimation on opacity {
                            running: capture.visible && capture.phase === "listening"
                            loops: Animation.Infinite
                            onRunningChanged: if (!running) micIcon.opacity = 1
                            NumberAnimation { to: 0.35; duration: 700; easing.type: Easing.InOutQuad }
                            NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutQuad }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text {
                        Layout.fillWidth: true
                        text: ({
                                "listening": "Listening…",
                                "transcribing": "Transcribing…",
                                "saving": "Saving…",
                                "saved": "Saved to notebook",
                                "failed": "Could not save"
                            })[capture.phase]
                        color: capture.phase === "failed" ? capture.statusColor : Theme.menuText
                        font { family: Theme.fontFamily; pixelSize: 15; weight: Font.DemiBold }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: capture.phase === "listening" ? "Release the dictation key when finished"
                            : capture.phase === "transcribing" ? "Turning your voice into a note"
                            : capture.phase === "saving" ? "Adding to your context notebook"
                            : capture.phase === "saved" ? "Captured in your context notebook"
                            : "Your transcript is still shown below"
                        color: Theme.menuSecondaryText
                        wrapMode: Text.Wrap
                        font { family: Theme.fontFamily; pixelSize: 12 }
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 1
                color: Theme.menuSeparator
            }

            TextArea {
                id: field
                Layout.fillWidth: true
                Layout.minimumHeight: 64
                Layout.maximumHeight: 200
                // Stays visible even while empty: a hidden item cannot hold
                // the keyboard focus Handy pastes into.
                wrapMode: TextEdit.Wrap
                color: Theme.menuText
                placeholderText: capture.phase === "listening" ? "Speak your thought…" : "Waiting for your transcript…"
                placeholderTextColor: Theme.menuSecondaryText
                selectionColor: "#0a84ff"
                selectedTextColor: "#ffffff"
                padding: 0
                background: null
                font { family: Theme.fontFamily; pixelSize: 14 }
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
                color: capture.statusColor
                font { family: Theme.fontFamily; pixelSize: 12 }
            }

            Text {
                Layout.fillWidth: true
                text: "Esc to discard"
                visible: capture.phase === "listening" || capture.phase === "transcribing"
                horizontalAlignment: Text.AlignRight
                color: Theme.menuSecondaryText
                font { family: Theme.fontFamily; pixelSize: 11 }
            }
        }
    }
}
