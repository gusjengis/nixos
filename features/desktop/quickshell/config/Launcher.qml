import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Widgets
import "state"
import "theme"

PanelWindow {
    id: launcher

    property string initialMode: "local"
    property string mode: initialMode
    property var host: null
    property var entries: []
    property var request: null
    property string error: ""
    property string providerError: ""
    property int searchGeneration: 0
    property var projectResults: []
    property var pendingProjectResults: []
    property var projectSearch: null
    property var usage: ({
            "apps": {},
            "projects": {}
        })
    property var ignoredDesktopEntryIds: ["wl-kbptr"]
    property var tools: [
        {
            "name": "Color Picker",
            "description": "Pick a screen color and copy its value",
            "icon": "color-select-symbolic",
            "instantClose": true,
            "command": ["hyprpicker", "--autocopy", "--remember-format"]
        },
        {
            "name": "Mirror",
            "description": "Show a mirrored, low-latency webcam view",
            "icon": "camera-web-symbolic",
            "command": ["mpv", "--title=Mirror", "--profile=low-latency", "--untimed", "--vf=hflip", "av://v4l2:/dev/video0"]
        }
    ]

    readonly property bool loading: request !== null
    readonly property var apps: mode === "local" ? DesktopEntries.applications.values.filter(app => !app.noDisplay && !ignoredDesktopEntryIds.includes(app.id.replace(/\.desktop$/, ""))) : mode === "tools" ? tools : entries
    readonly property var appResults: rankedApps()
    readonly property var webResults: mode === "local" && search.text.trim() !== "" ? [
        {
            "kind": "web",
            "name": "Search Google for \"" + search.text.trim() + "\"",
            "description": "Open in browser",
            "query": search.text.trim(),
            "count": 0
        }
    ] : []
    readonly property var results: mode === "local" ? appResults.concat(projectResults, webResults) : appResults
    readonly property var selectedResult: list.currentIndex >= 0 && list.currentIndex < results.length ? results[list.currentIndex] : null

    visible: false
    focusable: true
    exclusionMode: ExclusionMode.Ignore
    implicitWidth: Math.min(580, screen.width * 0.8)
    implicitHeight: Math.min(540, screen.height * 0.7)
    color: "transparent"
    WlrLayershell.namespace: initialMode === "tools" ? "quickshell-tools-launcher" : "quickshell-launcher"

    function appKey(app) {
        return app.id || app.name;
    }

    readonly property string separators: " -_/.\\:,@+"

    function normalizeText(value) {
        const lowered = value.toLowerCase();
        let normalized = "";
        for (let index = 0; index < lowered.length; index++)
            normalized += launcher.separators.includes(lowered[index]) ? " " : lowered[index];
        return normalized;
    }

    function tokenScore(candidate, token) {
        let position = -1;
        let score = 0;
        for (let index = 0; index < token.length; index++) {
            const next = candidate.indexOf(token[index], position + 1);
            if (next < 0)
                return -1;
            score += next === position + 1 ? 8 : 1;
            if (next === 0 || candidate[next - 1] === " ")
                score += 5;
            position = next;
        }
        return score;
    }

    function fuzzyScore(value, rawQuery) {
        const candidate = normalizeText(value);
        const tokens = normalizeText(rawQuery).split(" ").filter(token => token !== "");
        if (tokens.length === 0)
            return 0;
        let score = 0;
        for (let index = 0; index < tokens.length; index++) {
            const token = tokens[index];
            const matched = tokenScore(candidate, token);
            if (matched < 0)
                return -1;
            score += matched;
            if (candidate.indexOf(token) >= 0)
                score += token.length * 4;
            if (candidate.startsWith(token))
                score += 10;
        }
        return score - candidate.length * 0.01;
    }

    function rankedApps() {
        const query = search.text.trim();
        return apps.map(app => {
            const description = app.description || "";
            const key = appKey(app);
            const frequency = mode === "local" ? launcher.usage.apps[key] || {} : {};
            return {
                "kind": mode === "local" ? "app" : mode === "tools" ? "tool" : "remote",
                "name": app.name,
                "description": description,
                "iconData": app.iconData,
                "icon": app.icon,
                "target": app,
                "usageKey": key,
                "count": frequency.count || 0,
                "lastUsed": frequency.lastUsed || 0,
                "score": fuzzyScore(app.name + " " + description, query)
            };
        }).filter(result => result.score >= 0).sort((left, right) => right.count - left.count || right.lastUsed - left.lastUsed || right.score - left.score || left.name.localeCompare(right.name));
    }

    function loadUsage() {
        try {
            usage = JSON.parse(usageFile.text());
        } catch (loadError) {
            usage = ({
                    "apps": {},
                    "projects": {}
                });
        }
    }

    function cancelRequest() {
        if (request) {
            const previous = request;
            request = null;
            previous.destroy();
        }
    }

    function cancelSearch() {
        if (projectSearch) {
            projectSearch.destroy();
            projectSearch = null;
        }
    }

    function reset(nextMode) {
        cancelRequest();
        cancelSearch();
        mode = nextMode;
        entries = [];
        error = "";
        providerError = "";
        search.text = "";
        projectResults = [];
        list.currentIndex = 0;
        visible = true;
        search.forceActiveFocus();
        Qt.callLater(() => startProjectSearch());
    }

    function open(nextMode) {
        reset(nextMode);
        if (nextMode === "hosts") {
            host = null;
            load(["hosts"]);
        } else if (nextMode === "remote" && host) {
            load(["list", host.id]);
        }
    }

    function load(args) {
        request = RequestProcess.createObject(launcher, {
            command: ["quickshell-remote-apps"].concat(args),
            launcher: launcher
        });
        request.running = true;
    }

    function activate(index, currentWorkspace) {
        const result = results[index];
        if (!result || loading)
            return;
        if (mode === "hosts") {
            host = result.target;
            open("remote");
        } else if (mode === "remote") {
            const process = LaunchProcess.createObject(launcher, {
                command: ["quickshell-remote-apps", "start", host.id, result.target.id],
                appName: result.name,
                hostName: host.name,
                launcher: launcher
            });
            process.running = true;
            visible = false;
        } else if (result.kind === "app") {
            Quickshell.execDetached(["quickshell-search", "record-app", result.usageKey]);
            result.target.execute();
            visible = false;
        } else if (result.kind === "project") {
            const command = ["quickshell-search", "open-project", result.path, result.profile];
            if (currentWorkspace)
                command.push("--current");
            Quickshell.execDetached(command);
            visible = false;
        } else if (result.kind === "web") {
            Quickshell.execDetached(["quickshell-search", "web", result.query]);
            visible = false;
        } else if (result.kind === "tool") {
            if (result.target.instantClose) {
                colorPickerProcess.command = result.target.command;
                enableInstantClose.running = true;
            } else {
                visible = false;
                Quickshell.execDetached(result.target.command);
            }
        }
    }

    function activateCurrentWorkspace() {
        if (selectedResult && selectedResult.kind === "project")
            activate(list.currentIndex, true);
    }

    function startProjectSearch() {
        searchGeneration++;
        cancelSearch();
        projectResults = [];
        pendingProjectResults = [];
        providerError = "";
        if (!visible || mode !== "local")
            return;
        projectSearch = searchProcessComponent.createObject(launcher, {
            "launcher": launcher,
            "provider": "projects",
            "query": search.text.trim(),
            "generation": searchGeneration
        });
        projectSearch.running = true;
    }

    function enqueueResult(generation, _provider, data) {
        if (generation !== searchGeneration)
            return;
        try {
            pendingProjectResults.push(JSON.parse(data));
            if (!resultFlush.running)
                resultFlush.start();
        } catch (parseError) {
            console.warn("Cannot parse project search result:", parseError);
        }
    }

    function reportSearchError(generation, message) {
        if (generation !== searchGeneration)
            return;
        providerError = message.trim();
        console.warn("Project search:", providerError);
    }

    function flushResults() {
        if (pendingProjectResults.length > 0) {
            projectResults = projectResults.concat(pendingProjectResults);
            pendingProjectResults = [];
        }
    }

    HyprlandFocusGrab {
        id: focusGrab
        windows: [launcher]
        onCleared: {
            if (!FocusGuard.suspended)
                launcher.visible = false;
        }
    }

    onVisibleChanged: {
        if (visible)
            search.forceActiveFocus();
        else {
            searchGeneration++;
            searchTimer.stop();
            resultFlush.stop();
            cancelRequest();
            cancelSearch();
        }
    }

    Binding {
        target: focusGrab
        property: "active"
        value: launcher.visible && !FocusGuard.suspended
    }

    Component {
        id: searchProcessComponent
        SearchProcess {}
    }

    Process {
        id: enableInstantClose
        command: ["hyprctl", "--quiet", "eval", "colorPickerNoAnimationRule:set_enabled(true)"]
        onExited: {
            launcher.visible = false;
            colorPickerProcess.running = true;
        }
    }

    Process {
        id: colorPickerProcess
        onExited: disableInstantClose.running = true
    }

    Process {
        id: disableInstantClose
        command: ["hyprctl", "--quiet", "eval", "colorPickerNoAnimationRule:set_enabled(false)"]
    }

    Timer {
        interval: 35000
        running: launcher.loading
        onTriggered: {
            launcher.cancelRequest();
            launcher.error = "Request timed out. Check SSH access and rebuild both machines.";
        }
    }

    Timer {
        id: searchTimer
        interval: 100
        onTriggered: launcher.startProjectSearch()
    }

    Timer {
        id: resultFlush
        interval: 30
        onTriggered: launcher.flushResults()
    }

    FileView {
        id: usageFile
        path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/quickshell/launcher-usage.json"
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: launcher.loadUsage()
    }

    Rectangle {
        anchors.fill: parent
        color: Theme.background
        radius: Theme.radius * 2
        border.width: 1
        border.color: Theme.border
        clip: true

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12

            TextField {
                id: search
                Layout.fillWidth: true
                Layout.preferredHeight: 50
                placeholderText: mode === "hosts" ? "Search machines" : mode === "remote" ? "Search remote applications" : mode === "tools" ? "Search tools" : "Search apps, projects, and the web"
                placeholderTextColor: Theme.muted
                color: Theme.text
                selectionColor: Theme.accentStrong
                selectedTextColor: Theme.background
                leftPadding: 16
                rightPadding: 16
                font.pixelSize: 16
                focus: true
                background: Rectangle {
                    radius: Theme.radius
                    color: Theme.surface
                    border.width: 1
                    border.color: search.activeFocus ? Theme.accentStrong : Theme.border
                }
                onTextChanged: {
                    list.currentIndex = 0;
                    searchTimer.restart();
                }
                Keys.onDownPressed: list.incrementCurrentIndex()
                Keys.onUpPressed: list.decrementCurrentIndex()
                Keys.onEscapePressed: launcher.visible = false
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_N && (event.modifiers & Qt.ControlModifier) && launcher.selectedResult && launcher.selectedResult.kind === "project") {
                        launcher.activateCurrentWorkspace();
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Left && (event.modifiers & Qt.AltModifier)) {
                        if (mode === "remote")
                            launcher.open("hosts");
                        else if (mode === "hosts")
                            launcher.visible = false;
                        event.accepted = true;
                    }
                }
                onAccepted: launcher.activate(list.currentIndex, false)
            }

            Rectangle {
                Layout.fillWidth: true
                implicitHeight: statusText.implicitHeight + 20
                visible: launcher.error !== "" || launcher.providerError !== "" || (!launcher.loading && launcher.results.length === 0)
                radius: Theme.radius
                color: Theme.surfaceHover
                border.width: 1
                border.color: launcher.error !== "" || launcher.providerError !== "" ? Theme.danger : Theme.border

                Text {
                    id: statusText
                    anchors.fill: parent
                    anchors.margins: 10
                    text: launcher.error || launcher.providerError || "No matches"
                    color: launcher.error !== "" || launcher.providerError !== "" ? Theme.danger : Theme.muted
                    wrapMode: Text.Wrap
                }
            }

            ListView {
                id: list
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 4
                boundsBehavior: Flickable.StopAtBounds
                model: launcher.results
                currentIndex: 0
                highlightMoveDuration: 0
                ScrollBar.vertical: ScrollBar {}

                delegate: Rectangle {
                    id: resultRow
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    height: 62
                    radius: Theme.radius
                    color: resultRow.ListView.isCurrentItem || rowMouse.containsMouse ? Theme.surfaceHover : "transparent"
                    border.width: resultRow.ListView.isCurrentItem ? 1 : 0
                    border.color: Theme.accentStrong

                    RowLayout {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 10

                        Rectangle {
                            implicitWidth: 42
                            implicitHeight: 42
                            radius: Theme.radius
                            color: Theme.surface
                            border.width: 1
                            border.color: Theme.border

                            IconImage {
                                anchors.centerIn: parent
                                visible: modelData.kind === "app" || modelData.kind === "remote" || modelData.kind === "tool"
                                source: modelData.iconData || Quickshell.iconPath(modelData.icon || "application-x-executable", true)
                                implicitSize: 29
                            }

                            Text {
                                anchors.centerIn: parent
                                visible: modelData.kind !== "app" && modelData.kind !== "remote" && modelData.kind !== "tool"
                                text: modelData.kind === "project" ? "/" : ">"
                                color: modelData.kind === "web" ? Theme.accent : Theme.muted
                                font.pixelSize: 18
                                font.bold: true
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 2

                            Text {
                                Layout.fillWidth: true
                                text: modelData.name
                                textFormat: Text.PlainText
                                color: Theme.text
                                font.pixelSize: 14
                                font.bold: resultRow.ListView.isCurrentItem
                                elide: Text.ElideRight
                            }

                            Text {
                                Layout.fillWidth: true
                                text: modelData.description || ""
                                textFormat: Text.PlainText
                                color: Theme.muted
                                font.pixelSize: 11
                                elide: Text.ElideRight
                            }
                        }

                        Text {
                            text: modelData.kind.toUpperCase()
                            color: modelData.kind === "web" ? Theme.accent : Theme.muted
                            font.pixelSize: 9
                            font.bold: true
                        }
                    }

                    MouseArea {
                        id: rowMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onEntered: list.currentIndex = index
                        onClicked: launcher.activate(index, false)
                    }
                }
            }
        }
    }
}
