import QtQuick
import Quickshell
import Quickshell.Io
import "../state"

Scope {
    id: root
    property var sessions: []
    property string error: ""
    property bool loaded: false
    readonly property int attentionCount: sessions.filter(item => ["input", "error", "done"].includes(item.state)).length
    readonly property string attentionColor: sessions.some(item => item.state === "error") ? "#f85149"
        : sessions.some(item => item.state === "input") ? "#d29922" : "#3fb950"
    readonly property int workingCount: sessions.filter(item => item.state === "working").length
    readonly property string helper: Quickshell.shellDir + "/../opencode-sessions.py"
    property bool rendererReady: false
    property bool rendering: false
    property bool renderPending: true
    property var activePanel: null
    property int selected: -1
    readonly property int offset: 0
    property int cellWidth: 8
    property int cellHeight: 15
    property string bitmapPath: ""
    property int bitmapWidth: 560
    property int bitmapHeight: 120
    property int bitmapGeneration: -1
    property real renderMs: 0
    readonly property int rows: 4 + 4 * Math.max(1, sessions.length)
    readonly property int pageSize: Math.max(1, sessions.length)
    property int renderId: 0

    function render() {
        renderPending = true;
        if (!rendererReady || rendering || !raster.running) return;
        renderPending = false;
        rendering = true;
        raster.write(JSON.stringify({id: ++renderId, sessions: sessions,
            catalog: DesktopSessions.contextCatalog, rows: rows,
            frame: Math.floor(Date.now() / 80) % 10, selected: selected, offset: offset, error: error}) + "\n");
    }
    function showPanel(panel) { activePanel = panel; }
    function hidePanel(panel) {
        if (activePanel !== panel) return;
        activePanel = null;
        selected = -1;
    }
    function moveSelection(steps) {
        selected = Math.max(0, Math.min(sessions.length - 1, selected + steps));
    }
    onSessionsChanged: {
        render();
    }
    onSelectedChanged: render()
    onErrorChanged: render()
    Connections {
        target: DesktopSessions
        function onContextCatalogChanged() { root.render(); }
    }

    function refresh() { if (!request.running) request.running = true; }
    function focus(pane) {
        if (activation.running) return;
        activation.command = ["python3", helper, "focus", pane];
        activation.running = true;
    }

    IpcHandler {
        target: "opencodeOverview"
        function available(): bool { return DesktopFeatures.development && root.loaded && root.rendererReady && !root.error; }
        function snapshot(): string { return JSON.stringify(root.sessions); }
        function renderStats(): string {
            return JSON.stringify({ready: root.rendererReady, path: root.bitmapPath,
                width: root.bitmapWidth, height: root.bitmapHeight, cellWidth: root.cellWidth,
                cellHeight: root.cellHeight, generation: root.bitmapGeneration, renderMs: root.renderMs,
                active: root.activePanel !== null, rendering: root.rendering});
        }
    }
    Timer {
        interval: 80
        running: root.activePanel !== null && root.workingCount > 0
        repeat: true
        onTriggered: root.render()
    }
    Timer {
        id: rasterRetry
        interval: 1000
        onTriggered: if (DesktopFeatures.development) raster.running = true
    }
    Process {
        id: raster
        command: ["kitty", "+runpy", "import runpy; from pathlib import Path; runpy.run_path(str(Path("
            + JSON.stringify(Quickshell.shellDir + "/../opencode-renderer.py") + ").resolve()), run_name='__main__')"]
        running: DesktopFeatures.development
        stdinEnabled: true
        stdout: SplitParser {
            onRead: data => {
                try {
                    const response = JSON.parse(data);
                    if (response.ready) {
                        root.cellWidth = response.cellWidth;
                        root.cellHeight = response.cellHeight;
                        root.rendererReady = true;
                        root.render();
                        return;
                    }
                    root.bitmapWidth = response.width;
                    root.bitmapHeight = response.height;
                    root.bitmapPath = response.path;
                    root.renderMs = response.renderMs;
                    root.bitmapGeneration = response.generation;
                    root.rendering = false;
                    if (root.renderPending) root.render();
                } catch (error) { console.warn("OpenCode rasterizer:", error, data); }
            }
        }
        stderr: StdioCollector { onStreamFinished: if (text.trim()) console.warn("OpenCode rasterizer:", text.trim()) }
        onExited: {
            root.rendererReady = false;
            root.rendering = false;
            rasterRetry.restart();
        }
    }
    Timer {
        interval: 750
        running: DesktopFeatures.development
        repeat: true
        triggeredOnStart: true
        onTriggered: root.refresh()
    }
    Process {
        id: request
        command: ["python3", root.helper]
        stdout: StdioCollector { id: output }
        stderr: StdioCollector { id: errors }
        onExited: (code) => {
            if (code !== 0) { root.error = errors.text.trim() || "Cannot read live sessions"; return; }
            try {
                const next = JSON.parse(output.text);
                if (JSON.stringify(next) !== JSON.stringify(root.sessions))
                    root.sessions = next;
                root.loaded = true;
                root.error = "";
            } catch (error) { root.error = String(error); }
        }
    }
    Process {
        id: activation
        stderr: StdioCollector { id: activationErrors }
        onExited: (code) => {
            if (code !== 0) root.error = activationErrors.text.trim() || "Cannot focus session";
            root.refresh();
        }
    }
}
