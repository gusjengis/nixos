import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import "state"
import "theme"
import "widgets"

PanelWindow {
    id: picker

    visible: false
    focusable: true
    exclusionMode: ExclusionMode.Ignore
    implicitWidth: screen.width * 0.5
    implicitHeight: screen.height / 3 + 108
    color: "transparent"
    WlrLayershell.namespace: "quickshell-wallpaper-picker"

    // Every wallpaper in the persisted random order, decorated with metadata.
    property var allWallpapers: []
    // The subset currently shown by the carousel; equals allWallpapers when the query is empty.
    property var wallpapers: []
    property var catalogEntries: []
    property var metadata: ({})
    property string metadataPath: ""
    // Filenames the user hid with Ctrl+D, mirrored from ~/Wallpapers/curation.json.
    property var hiddenFiles: ({})
    property string curationPath: ""
    property string notice: ""
    property int poolSize: 0
    property real animatedIndex: 0
    property string originalWallpaper: ""
    property bool ready: false
    property bool armed: false
    readonly property string rawQuery: search.text.trim()
    // "is:hidden" is a mode switch rather than a search term: it swaps the
    // carousel over to what has been hidden so it can be restored.
    readonly property bool showingHidden: /(^|\s)is:hidden(\s|$)/i.test(rawQuery)
    readonly property string query: rawQuery.replace(/(^|\s)is:hidden(\s|$)/gi, " ").trim()
    readonly property bool filtering: query !== "" || showingHidden
    readonly property int selectedIndex: {
        if (wallpapers.length === 0)
            return 0;
        const index = Math.round(animatedIndex) % wallpapers.length;
        return index < 0 ? index + wallpapers.length : index;
    }
    readonly property var selected: wallpapers.length === 0 ? null : wallpapers[selectedIndex]
    readonly property string selectedPath: selected ? selected.path : ""

    function show() {
        ready = false;
        armed = false;
        search.text = "";
        const focusedMonitor = Hyprland.focusedMonitor;
        if (focusedMonitor) {
            for (let index = 0; index < Quickshell.screens.length; index++) {
                const candidate = Quickshell.screens[index];
                if (candidate.name === focusedMonitor.name) {
                    screen = candidate;
                    break;
                }
            }
        }
        visible = true;
        if (!catalog.running)
            catalog.running = true;
    }

    function toggle() {
        if (visible)
            dismiss();
        else
            show();
    }

    function dismiss() {
        applySelected();
    }

    function restoreOriginal() {
        previewTimer.stop();
        if (originalWallpaper !== "")
            Quickshell.execDetached(["wallpaperctl", "set", originalWallpaper]);
        visible = false;
    }

    function select(offset) {
        if (wallpapers.length === 0)
            return;
        animatedIndex = Math.round(animatedIndex) + offset;
    }

    // Applying writes the wallpaper to the state file, which is also what anchors the
    // random cycle, so the next open lands on this wallpaper's slot in the random order.
    function applySelected() {
        if (selectedPath === "") {
            visible = false;
            return;
        }
        previewTimer.stop();
        Quickshell.execDetached(["wallpaperctl", "set", selectedPath]);
        visible = false;
    }

    function selectRandom() {
        if (wallpapers.length === 0)
            return;
        animatedIndex = Math.floor(Math.random() * wallpapers.length);
    }

    // Ctrl+D. Hiding removes a wallpaper from the picker and from the cycle
    // without deleting the file, so it stays reversible: "is:hidden" lists what
    // is hidden and Ctrl+D there puts it back.
    function toggleHiddenSelected() {
        const entry = selected;
        if (!entry)
            return;
        const nowHidden = !hiddenFiles[entry.file];

        // Anchor on the neighbour before refiltering. applyFilter falls back to
        // index 0 when the kept path disappears, which would throw the carousel
        // back to the start of the library on every hide.
        const neighbour = wallpapers.length > 1 ? wallpapers[(selectedIndex + 1) % wallpapers.length] : null;

        // Applied optimistically: waiting for the process and the curation file
        // watcher to come back would leave the hidden wallpaper on screen.
        const updated = Object.assign({}, hiddenFiles);
        if (nowHidden)
            updated[entry.file] = true;
        else
            delete updated[entry.file];
        hiddenFiles = updated;
        entry.hidden = nowHidden;

        applyFilter(neighbour ? neighbour.path : "");
        notice = nowHidden ? "Hidden - Ctrl+D restores it, or search is:hidden" : "Restored";
        noticeTimer.restart();

        // Writes curation.json and pushes it; detached so the picker never
        // waits on git.
        Quickshell.execDetached(["wallpaper-hide", entry.path]);
    }

    function normalizeText(value) {
        return (value || "").toLowerCase().replace(/[^0-9a-z\u00c0-\u024f]+/g, " ").trim();
    }

    function loadMetadata() {
        try {
            const parsed = JSON.parse(metadataView.text());
            metadata = parsed.entries || {};
        } catch (error) {
            console.warn("Cannot load wallpaper metadata:", error);
            metadata = ({});
        }
        rebuild();
    }

    // Also runs when another machine's hide arrives through the hourly sync.
    function loadCuration() {
        try {
            const parsed = JSON.parse(curationView.text());
            hiddenFiles = parsed.hidden || {};
        } catch (error) {
            hiddenFiles = ({});
        }
        rebuild();
    }

    // Joins the catalog with the Peapix metadata and precomputes the search haystacks
    // once per open so filtering stays cheap on every keystroke.
    function rebuild() {
        const entries = [];
        for (let index = 0; index < catalogEntries.length; index++) {
            const item = catalogEntries[index];
            const record = metadata[item.file] || null;
            const tags = record && record.tags ? record.tags : [];
            // Bing publishes a different image per market on many days, so a
            // large part of the library only ever had German, Japanese, French
            // and so on. English is preferred for display and search where a
            // translation exists; the original still feeds the haystack so
            // searching in the source language keeps working.
            const originalTitle = record && record.title ? record.title : item.name;
            const title = record && record.englishTitle ? record.englishTitle : originalTitle;
            const headline = record && (record.englishHeadline || record.headline) ? record.englishHeadline || record.headline : "";
            const description = record && (record.englishDescription || record.description) ? record.englishDescription || record.description : "";
            const date = record && record.date ? record.date : "";
            entries.push({
                "path": item.path,
                "file": item.file,
                "name": item.name,
                "extension": item.extension,
                "order": index,
                "hidden": !!hiddenFiles[item.file],
                "title": title,
                "headline": headline,
                "date": date,
                "tags": tags,
                "titleText": normalizeText(title === originalTitle ? title : title + " " + originalTitle),
                "tagText": normalizeText(tags.join(" ")),
                "bodyText": normalizeText([headline, description, record && record.headline ? record.headline : "", record && record.description ? record.description : "", item.name, date].join(" "))
            });
        }
        allWallpapers = entries;
        applyFilter(armed ? selectedPath : originalWallpaper);
    }

    function matchScore(entry, terms) {
        let score = 0;
        for (let index = 0; index < terms.length; index++) {
            const term = terms[index];
            let best = -1;
            if (entry.titleText.indexOf(term) >= 0)
                best = entry.titleText.startsWith(term) || entry.titleText.indexOf(" " + term) >= 0 ? 120 : 90;
            if (entry.tagText.indexOf(term) >= 0)
                best = Math.max(best, 70);
            if (entry.bodyText.indexOf(term) >= 0)
                best = Math.max(best, 20);
            if (best < 0)
                return -1;
            score += best;
        }
        return score;
    }

    // Narrows the carousel to the query, keeping the previously centered wallpaper
    // centered whenever it survives the filter.
    function applyFilter(preferredPath) {
        const keep = preferredPath !== undefined && preferredPath !== "" ? preferredPath : selectedPath;
        const terms = normalizeText(query).split(" ").filter(term => term !== "");

        // Hidden wallpapers stay in allWallpapers so toggling "is:hidden" is a
        // refilter rather than a rebuild, but only one side is ever on screen.
        const pool = allWallpapers.filter(entry => entry.hidden === showingHidden);
        poolSize = pool.length;

        let results;
        if (terms.length === 0) {
            results = pool;
        } else {
            results = pool.map(entry => ({
                        "entry": entry,
                        "score": matchScore(entry, terms)
                    })).filter(result => result.score >= 0).sort((left, right) => right.score - left.score || left.entry.order - right.entry.order).map(result => result.entry);
        }

        ready = false;
        wallpapers = results;
        const target = results.findIndex(entry => entry.path === keep);
        animatedIndex = target >= 0 ? target : 0;
        Qt.callLater(() => picker.ready = true);
    }

    function previewSelected() {
        if (!armed || !visible || selectedPath === "")
            return;
        previewTimer.path = selectedPath;
        previewTimer.restart();
    }

    onSelectedPathChanged: previewSelected()

    onVisibleChanged: {
        if (visible)
            search.forceActiveFocus();
        else
            previewTimer.stop();
    }

    HyprlandFocusGrab {
        id: focusGrab
        windows: [picker]
        onCleared: {
            if (!FocusGuard.suspended)
                picker.dismiss();
        }
    }

    Binding {
        target: focusGrab
        property: "active"
        value: picker.visible && !FocusGuard.suspended
    }

    Process {
        id: catalog
        command: ["wallpaperctl", "catalog"]
        stdout: StdioCollector { id: catalogOutput }
        onExited: (code, status) => {
            if (code !== 0 || status !== 0)
                return;
            try {
                const result = JSON.parse(catalogOutput.text);
                picker.catalogEntries = result.wallpapers || [];
                picker.originalWallpaper = result.current || "";
                picker.metadataPath = result.metadataFile || "";
                picker.curationPath = result.curationFile || "";
                // Seeded from the catalog so the first frame already excludes
                // hidden wallpapers, before curation.json has been read.
                const seeded = {};
                for (let index = 0; index < picker.catalogEntries.length; index++) {
                    const item = picker.catalogEntries[index];
                    if (item.hidden)
                        seeded[item.file] = true;
                }
                picker.hiddenFiles = seeded;
                picker.rebuild();
                if (picker.metadataPath !== "" && Object.keys(picker.metadata).length === 0)
                    metadataView.reload();
                Qt.callLater(() => {
                    picker.ready = true;
                    picker.armed = true;
                });
            } catch (error) {
                console.warn("Cannot load wallpaper catalog:", error);
            }
        }
    }

    FileView {
        id: metadataView
        path: picker.metadataPath
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: picker.loadMetadata()
    }

    // printErrors stays off because curation.json legitimately does not exist
    // until the first Ctrl+D.
    FileView {
        id: curationView
        path: picker.curationPath
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: picker.loadCuration()
    }

    Timer {
        id: noticeTimer
        interval: 2600
        onTriggered: picker.notice = ""
    }

    Timer {
        id: previewTimer
        property string path: ""
        interval: 120
        onTriggered: {
            if (picker.visible && path !== "")
                Quickshell.execDetached(["wallpaperctl", "preview", path]);
        }
    }

    Behavior on animatedIndex {
        enabled: picker.ready
        NumberAnimation { duration: 190; easing.type: Easing.OutCubic }
    }

    Item {
        id: stage
        anchors.fill: parent

        Item {
            id: searchRow
            anchors.top: parent.top
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(560, stage.width * 0.6)
            height: 36

            ThemedTextField {
                id: search
                anchors.fill: parent
                focus: true
                placeholderText: "Search wallpapers"
                font.pixelSize: 14
                rightPadding: resultCount.width + 24
                onTextChanged: filterTimer.restart()

                // Handled here rather than with Shortcut so typing a query never triggers navigation.
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_Left || event.key === Qt.Key_Up) {
                        picker.select(-1);
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Right || event.key === Qt.Key_Down) {
                        picker.select(1);
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Escape) {
                        if (search.text !== "")
                            search.text = "";
                        else
                            picker.applySelected();
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Backspace && search.text === "") {
                        picker.restoreOriginal();
                        event.accepted = true;
                    } else if (event.key === Qt.Key_R && (event.modifiers & Qt.ControlModifier)) {
                        picker.selectRandom();
                        event.accepted = true;
                    } else if (event.key === Qt.Key_D && (event.modifiers & Qt.ControlModifier)) {
                        picker.toggleHiddenSelected();
                        event.accepted = true;
                    }
                }
                onAccepted: picker.applySelected()
            }

            Text {
                id: resultCount
                anchors.right: parent.right
                anchors.rightMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                visible: picker.filtering
                text: picker.wallpapers.length + "/" + picker.poolSize + (picker.showingHidden ? " hidden" : "")
                color: picker.wallpapers.length === 0 ? Theme.danger : Theme.muted
                font.family: Theme.fontFamily
                font.pixelSize: 11
            }
        }

        Timer {
            id: filterTimer
            interval: 90
            onTriggered: picker.applyFilter()
        }

        Item {
            id: caption
            anchors.bottom: parent.bottom
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(560, stage.width * 0.6)
            height: 52
            visible: picker.selected !== null

            Rectangle {
                anchors.fill: parent
                color: Qt.rgba(Theme.background.r, Theme.background.g, Theme.background.b, 0.88)
                border.color: Theme.border
                border.width: 1
                radius: 10
            }

            Text {
                id: captionTitle
                anchors.top: parent.top
                anchors.topMargin: 7
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width - 24
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: picker.selected ? picker.selected.title : ""
                color: Theme.text
                font.family: Theme.fontFamily
                font.pixelSize: 15
                font.bold: true
            }

            Text {
                anchors.top: captionTitle.bottom
                anchors.topMargin: 2
                anchors.horizontalCenter: parent.horizontalCenter
                width: parent.width - 24
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                visible: text !== ""
                // The transient Ctrl+D confirmation takes over this line, since
                // a separate popup would break the picker's focus grab.
                text: picker.notice !== "" ? picker.notice : picker.selected ? picker.selected.date : ""
                color: picker.notice !== "" ? Theme.accent : Theme.muted
                font.family: Theme.fontFamily
                font.pixelSize: 11
            }
        }

        Text {
            anchors.centerIn: parent
            visible: picker.wallpapers.length === 0
            text: picker.showingHidden && picker.query === "" ? "Nothing is hidden" : picker.filtering ? "No wallpapers match \"" + picker.query + "\"" : catalog.running ? "Loading wallpapers..." : "No wallpapers found in ~/Wallpapers"
            color: Theme.muted
            font.family: Theme.fontFamily
            font.pixelSize: 14
        }

        Item {
            id: carousel
            anchors.top: searchRow.bottom
            anchors.topMargin: 8
            anchors.bottom: caption.top
            anchors.bottomMargin: 4
            anchors.left: parent.left
            anchors.right: parent.right
            clip: true

            Repeater {
                model: 11

                delegate: Item {
                    id: card

                    readonly property int count: picker.wallpapers.length
                    readonly property int rawIndex: Math.floor((picker.animatedIndex - index + 5.5) / 11) * 11 + index
                    readonly property int wallpaperIndex: count === 0 ? 0 : ((rawIndex % count) + count) % count
                    readonly property var wallpaper: count === 0 ? null : picker.wallpapers[wallpaperIndex]
                    readonly property real distance: rawIndex - picker.animatedIndex
                    readonly property real absoluteDistance: Math.abs(distance)
                    readonly property real centerProgress: Math.sin(Math.max(0, 1 - Math.min(1, absoluteDistance)) * Math.PI / 2)
                    readonly property bool centered: absoluteDistance < 0.5
                    readonly property real sideWidth: carousel.width * 0.05
                    readonly property real centerWidth: carousel.height * 0.88 * 16 / 9
                    readonly property real stepGap: (centerWidth + sideWidth) / 2 * 1.02
                    readonly property real cardWidth: sideWidth + centerProgress * (centerWidth - sideWidth)
                    readonly property real step: absoluteDistance <= 1
                        ? distance * stepGap
                        : (distance < 0 ? -1 : 1) * (stepGap + (absoluteDistance - 1) * carousel.width * 0.055)

                    width: cardWidth
                    height: carousel.height * 0.88
                    x: carousel.width / 2 - width / 2 + step
                    y: carousel.height / 2 - height / 2
                    z: 100 - Math.round(absoluteDistance * 10)
                    opacity: Math.max(0, 1 - absoluteDistance / 5.5)
                    // The last clause stops a short result set from repeating across every card.
                    visible: count > 0 && opacity > 0 && absoluteDistance < Math.max(0.5, count / 2)

                    Rectangle {
                        id: cardMask
                        anchors.fill: parent
                        radius: Theme.radius
                        visible: false
                        // layer.enabled forces an off-screen render even though the item
                        // itself is invisible, which is what MultiEffect samples as a mask.
                        layer.enabled: true
                    }

                    Image {
                        id: cardArt
                        anchors.fill: parent
                        source: card.wallpaper ? "file://" + card.wallpaper.path : ""
                        sourceSize.width: 1200
                        sourceSize.height: 700
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        cache: true

                        layer.enabled: true
                        layer.effect: MultiEffect {
                            maskEnabled: true
                            maskSource: cardMask
                        }
                    }

                    Rectangle {
                        anchors.fill: parent
                        radius: Theme.radius
                        color: "transparent"
                        border.width: card.centered ? 2 : 1
                        border.color: card.centered ? Theme.accentStrong : Theme.border
                    }

                    MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        property real pressX: 0
                        property real startIndex: 0
                        property bool dragged: false

                        onPressed: mouse => {
                            pressX = card.mapToItem(stage, mouse.x, mouse.y).x;
                            startIndex = picker.animatedIndex;
                            dragged = false;
                        }
                        onPositionChanged: mouse => {
                            if (!pressed)
                                return;
                            const position = card.mapToItem(stage, mouse.x, mouse.y).x;
                            if (Math.abs(position - pressX) > 8)
                                dragged = true;
                            if (dragged)
                                picker.animatedIndex = startIndex - (position - pressX) / 145;
                        }
                        onReleased: {
                            if (dragged)
                                picker.animatedIndex = Math.round(picker.animatedIndex);
                        }
                        onClicked: {
                            if (dragged)
                                return;
                            if (card.centered)
                                picker.applySelected();
                            else
                                picker.animatedIndex = card.rawIndex;
                        }
                        onWheel: wheel => picker.select(wheel.angleDelta.y < 0 ? 1 : -1)
                    }
                }
            }
        }
    }
}
