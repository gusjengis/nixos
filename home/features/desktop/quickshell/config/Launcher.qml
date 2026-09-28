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
import "widgets"

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
    // Spotlight sits in the upper third, centred. The surface is sized for
    // the tallest results list; everything outside the glass shapes is
    // transparent, unblurred (ignore_alpha) and masked out of input.
    anchors.top: true
    margins.top: Math.round(screen.height * 0.2)
    implicitWidth: Math.min(680, screen.width * 0.8)
    implicitHeight: Math.min(600, screen.height * 0.7)
    color: "transparent"
    mask: Region { item: spotlight }

    // Local mode behaves like Spotlight: just the field until you type.
    // The other modes are pickers, so they always list their entries.
    readonly property bool showResults: mode !== "local" || search.text.trim() !== ""
    readonly property color selectionBlue: "#0a84ff"
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
            const description = app.description || app.comment || app.genericName || "";
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
        }).filter(result => result.score >= 0).sort((left, right) => {
            if (query === "")
                return right.count - left.count || right.lastUsed - left.lastUsed || left.name.localeCompare(right.name);
            return right.score - left.score || left.name.localeCompare(right.name);
        });
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
        request = requestProcessComponent.createObject(launcher, {
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
            const process = launchProcessComponent.createObject(launcher, {
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
        id: requestProcessComponent
        RequestProcess {}
    }

    Component {
        id: launchProcessComponent
        LaunchProcess {}
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

    function sectionTitle(index) {
        const result = results[index];
        if (!result)
            return "";
        if (mode === "local" && index === 0)
            return "Top Hit";
        if (mode === "hosts")
            return "Machines";
        if (mode === "tools")
            return "Tools";
        return {
            "app": "Applications",
            "remote": "Applications",
            "project": "Projects",
            "web": "Search the Web"
        }[result.kind] || "";
    }

    component Glass: Rectangle {
        color: Theme.background
        border { width: 1; color: Qt.rgba(1, 1, 1, 0.14) }
    }

    Column {
        id: spotlight
        width: parent.width
        spacing: 8

        // Search field: a free-floating glass capsule.
        Glass {
            width: parent.width
            height: 54
            radius: height / 2

            RowLayout {
                anchors { fill: parent; leftMargin: 18; rightMargin: 14 }
                spacing: 12

                SFSymbol {
                    symbol: "magnifyingglass"
                    size: 20
                    color: Theme.muted
                }

                TextField {
                    id: search
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    placeholderText: mode === "hosts" ? "Search Machines" : mode === "remote" ? "Search Remote Applications" : mode === "tools" ? "Search Tools" : "Spotlight Search"
                    placeholderTextColor: Theme.muted
                    color: Theme.text
                    selectionColor: launcher.selectionBlue
                    selectedTextColor: "#ffffff"
                    padding: 0
                    verticalAlignment: TextInput.AlignVCenter
                    font { family: Theme.fontFamily; pixelSize: 22 }
                    focus: true
                    background: null
                    onTextChanged: {
                        list.currentIndex = 0;
                        searchTimer.restart();
                    }
                    Keys.onDownPressed: list.incrementCurrentIndex()
                    Keys.onUpPressed: list.decrementCurrentIndex()
                    Keys.onEscapePressed: {
                        if (text !== "")
                            text = "";
                        else
                            launcher.visible = false;
                    }
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

                // Clear button, like xmark.circle.fill.
                Rectangle {
                    visible: search.text !== ""
                    implicitWidth: 18
                    implicitHeight: 18
                    radius: 9
                    color: Theme.muted
                    opacity: clearMouse.containsMouse ? 1 : 0.7

                    SFSymbol {
                        anchors.centerIn: parent
                        symbol: "xmark"
                        size: 8
                        font.weight: Font.Bold
                        color: Theme.backgroundBase
                    }

                    MouseArea {
                        id: clearMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            search.text = "";
                            search.forceActiveFocus();
                        }
                    }
                }
            }
        }

        // Results: a separate glass panel under the field.
        Glass {
            width: parent.width
            visible: launcher.showResults && (list.count > 0 || statusText.visible)
            height: Math.min(list.contentHeight + 16, 440) + (statusText.visible ? statusText.implicitHeight + 24 : 0)
            radius: 22
            clip: true

            Text {
                id: statusText
                anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16; topMargin: 12 }
                visible: launcher.error !== "" || launcher.providerError !== "" || (!launcher.loading && launcher.results.length === 0)
                text: launcher.error || launcher.providerError || "No Results"
                color: launcher.error !== "" || launcher.providerError !== "" ? Theme.danger : Theme.muted
                wrapMode: Text.Wrap
                font { family: Theme.fontFamily; pixelSize: 13 }
            }

            ListView {
                id: list
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom; top: statusText.visible ? statusText.bottom : parent.top; margins: 8 }
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                model: launcher.results
                currentIndex: 0
                highlightMoveDuration: 0
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Column {
                    id: entry

                    required property var modelData
                    required property int index
                    readonly property bool selected: ListView.isCurrentItem
                    readonly property bool topHit: launcher.mode === "local" && index === 0
                    readonly property string header: launcher.sectionTitle(index)
                    readonly property bool firstInSection: index === 0 || header !== launcher.sectionTitle(index - 1)

                    width: ListView.view.width

                    Text {
                        visible: entry.firstInSection && entry.header !== ""
                        leftPadding: 10
                        topPadding: entry.index === 0 ? 4 : 10
                        bottomPadding: 4
                        text: entry.header
                        color: Theme.muted
                        font { family: Theme.fontFamily; pixelSize: 12; weight: Font.DemiBold }
                    }

                    Rectangle {
                        width: parent.width
                        height: entry.topHit ? 52 : 34
                        radius: 10
                        color: entry.selected ? launcher.selectionBlue : "transparent"

                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 12 }
                            spacing: 10

                            Item {
                                readonly property string appIcon: entry.modelData.iconData || Quickshell.iconPath(entry.modelData.icon || "application-x-executable", true)
                                implicitWidth: entry.topHit ? 36 : 22
                                implicitHeight: implicitWidth

                                IconImage {
                                    anchors.fill: parent
                                    visible: entry.modelData.kind !== "tool" && parent.appIcon !== ""
                                    source: parent.appIcon
                                    implicitSize: parent.width
                                }

                                SFSymbol {
                                    anchors.centerIn: parent
                                    visible: entry.modelData.kind === "project" || entry.modelData.kind === "web" || entry.modelData.kind === "tool" || parent.appIcon === ""
                                    symbol: entry.modelData.kind === "project" ? "folder.fill" : entry.modelData.kind === "web" ? "globe" : entry.modelData.kind === "tool" ? (entry.modelData.name === "Color Picker" ? "eyedropper" : "camera.fill") : "square.grid.2x2.fill"
                                    size: parent.width * 0.8
                                    color: entry.selected ? "#ffffff" : Theme.muted
                                }
                            }

                            Text {
                                Layout.fillWidth: true
                                text: entry.modelData.name
                                textFormat: Text.PlainText
                                color: entry.selected ? "#ffffff" : Theme.text
                                elide: Text.ElideRight
                                font { family: Theme.fontFamily; pixelSize: entry.topHit ? 15 : 14; weight: entry.topHit ? Font.DemiBold : Font.Normal }
                            }

                            Text {
                                Layout.maximumWidth: entry.width * 0.4
                                visible: text !== ""
                                text: entry.modelData.description || ""
                                textFormat: Text.PlainText
                                color: entry.selected ? Qt.rgba(1, 1, 1, 0.75) : Theme.muted
                                elide: Text.ElideMiddle
                                font { family: Theme.fontFamily; pixelSize: 12 }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            onEntered: list.currentIndex = entry.index
                            onClicked: launcher.activate(entry.index, false)
                        }
                    }
                }
            }
        }
    }
}
