import QtQuick
import Quickshell.Io

QtObject {
    id: root

    property string contextId: ""
    property var cards: []
    property string error: ""
    property bool loaded: false
    readonly property bool busy: request.running

    onContextIdChanged: {
        cards = [];
        error = "";
        loaded = false;
        refresh();
    }

    function refresh() {
        if (!contextId || request.running)
            return;
        request.owner = contextId;
        request.offset = 0;
        request.phase = "In-Progress";
        request.collected = [];
        request.running = true;
    }

    function openCard(path) {
        if (!contextId || opening.running)
            return;
        opening.owner = contextId;
        opening.notePath = path;
        opening.running = true;
    }

    property var poll: Timer {
        interval: 5000
        repeat: true
        running: root.contextId !== ""
        onTriggered: root.refresh()
    }

    property var request: Process {
        id: request
        property string owner: ""
        property int offset: 0
        property string phase: "In-Progress"
        property var collected: []
        command: ["context-notes", "--context", owner, "list"]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify({ status: phase, offset: offset }));
            stdinEnabled = false;
        }
        onRunningChanged: { if (!running) stdinEnabled = true; }
        stdout: StdioCollector { id: output }
        stderr: StdioCollector { id: errors }
        onExited: (code, status) => {
            // Never publish a late response into a different context's desktop.
            if (owner !== root.contextId) {
                Qt.callLater(root.refresh);
                return;
            }
            try {
                if (code !== 0 || status !== 0)
                    throw new Error(errors.text.trim() || "Notebook unavailable");
                const value = JSON.parse(output.text);
                if (value.context_id !== owner || !Array.isArray(value.notes))
                    throw new Error("Invalid notebook response");
                collected = collected.concat(value.notes);
                if (value.next_offset !== null && value.next_offset > offset) {
                    offset = value.next_offset;
                    Qt.callLater(() => {
                        if (owner === root.contextId) running = true;
                        else root.refresh();
                    });
                    return;
                }
                if (phase === "In-Progress") {
                    phase = "Todo";
                    offset = 0;
                    Qt.callLater(() => {
                        if (owner === root.contextId) running = true;
                        else root.refresh();
                    });
                    return;
                }
                // Avoid rebuilding delegates on every poll of an unchanged board.
                if (JSON.stringify(root.cards) !== JSON.stringify(collected))
                    root.cards = collected;
                root.error = "";
            } catch (error) {
                root.cards = [];
                root.error = error.message;
            }
            root.loaded = true;
        }
    }

    property var opening: Process {
        id: opening
        property string owner: ""
        property string notePath: ""
        command: ["context-notes", "--context", owner, "open"]
        stdinEnabled: true
        onStarted: {
            write(JSON.stringify({ path: notePath }));
            stdinEnabled = false;
        }
        onRunningChanged: { if (!running) stdinEnabled = true; }
        stderr: StdioCollector { id: openErrors }
        onExited: (code, status) => {
            if (owner === root.contextId && (code !== 0 || status !== 0))
                root.error = openErrors.text.trim() || "Could not open note";
        }
    }
}
