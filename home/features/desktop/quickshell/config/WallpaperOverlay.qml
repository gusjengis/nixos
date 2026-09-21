import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Wayland
import "state"
import "theme"

// Wallpaper picker that uses the desktop itself as the preview surface: moving
// through the library sets the real wallpaper through `wallpaperctl preview`,
// and the overlay only draws the title (tvOS aerial style, bottom left) plus a
// search field that fades in once something is typed.
//
// The previous carousel UI is preserved, unused, in WallpaperPicker.qml.
PanelWindow {
    id: overlay

    visible: false
    focusable: true
    exclusionMode: ExclusionMode.Ignore
    color: "transparent"
    WlrLayershell.namespace: "quickshell-wallpaper-overlay"
    BackgroundEffect.blurRegion: overlay.rawQuery === "" || overlay.accepting ? null : searchBlurRegion
    anchors {
        top: true
        bottom: true
        left: true
        right: true
    }

    // tvOS-ish typography. Kept as properties because the right size depends on
    // the display and is worth tuning by hand.
    readonly property int titleSize: 44
    readonly property int titleWeight: Font.DemiBold
    readonly property int edgeMargin: 72
    readonly property int bottomMargin: 64

    // Every wallpaper in the persisted random order, decorated with metadata.
    property var allWallpapers: []
    // The subset the query selects; equals allWallpapers when the query is empty.
    property var wallpapers: []
    property var catalogEntries: []
    property var metadata: ({})
    property string metadataPath: ""
    // Filenames the user hid with Ctrl+D, mirrored from ~/Wallpapers/curation.json.
    property var hiddenFiles: ({})
    property string curationPath: ""
    property string notice: ""
    property int poolSize: 0
    property int index: 0
    property string originalWallpaper: ""
    // What hyprpaper is actually showing, so closing on an unchanged image can
    // skip the redundant hyprctl call that would otherwise flash.
    property string displayedPath: ""
    // Gates preview so opening the overlay never re-sets the wallpaper that is
    // already on screen.
    property bool armed: false
    property bool accepting: false
    readonly property string rawQuery: search.text.trim()
    // "is:hidden" is a mode switch rather than a search term: it swaps the list
    // over to what has been hidden so it can be restored.
    readonly property bool showingHidden: /(^|\s)is:hidden(\s|$)/i.test(rawQuery)
    readonly property string query: rawQuery.replace(/(^|\s)is:hidden(\s|$)/gi, " ").trim()
    readonly property bool filtering: query !== "" || showingHidden
    readonly property int selectedIndex: {
        if (wallpapers.length === 0)
            return 0;
        const wrapped = index % wallpapers.length;
        return wrapped < 0 ? wrapped + wallpapers.length : wrapped;
    }
    readonly property var selected: wallpapers.length === 0 ? null : wallpapers[selectedIndex]
    readonly property string selectedPath: selected ? selected.path : ""

    Region {
        id: searchBlurRegion
        x: searchRow.x
        y: searchRow.y
        width: searchRow.width
        height: searchRow.height
        radius: 18
    }

    function show() {
        armed = false;
        accepting = false;
        search.text = "";
        notice = "";
        // Cleared rather than kept: the 5-minute cycle may have changed the
        // wallpaper since the last open, so nothing is known until the catalog
        // reports `current` again.
        displayedPath = "";
        const focusedMonitor = Hyprland.focusedMonitor;
        if (focusedMonitor) {
            for (let i = 0; i < Quickshell.screens.length; i++) {
                const candidate = Quickshell.screens[i];
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

    // True when hyprpaper is known to already be showing `path`. A queued preview
    // means the screen is about to change, so nothing can be assumed.
    function isDisplayed(path) {
        return !previewTimer.running && path !== "" && path === displayedPath;
    }

    function restoreOriginal() {
        previewTimer.stop();
        if (originalWallpaper !== "" && originalWallpaper !== displayedPath)
            Quickshell.execDetached(["wallpaperctl", "set", originalWallpaper]);
        visible = false;
    }

    function select(offset) {
        if (wallpapers.length === 0)
            return;
        const count = wallpapers.length;
        index = ((index + offset) % count + count) % count;
    }

    // Applying writes the wallpaper to the state file, which is also what anchors
    // the random cycle, so the next open lands on this wallpaper's slot in the
    // random order.
    function applySelected() {
        if (selectedPath === "") {
            visible = false;
            return;
        }
        // `commit` writes the state files without going through hyprpaper, which
        // is all that is left to do when the preview already put this wallpaper
        // on screen.
        const command = isDisplayed(selectedPath) ? "commit" : "set";
        previewTimer.stop();
        Quickshell.execDetached(["wallpaperctl", command, selectedPath]);
        visible = false;
    }

    function selectRandom() {
        if (wallpapers.length === 0)
            return;
        index = Math.floor(Math.random() * wallpapers.length);
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
        // index 0 when the kept path disappears, which would throw the selection
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

        // Writes curation.json and pushes it; detached so the overlay never waits
        // on git.
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

    // Joins the catalog with the Peapix metadata and precomputes the search
    // haystacks once per open so filtering stays cheap on every keystroke.
    function rebuild() {
        const entries = [];
        for (let i = 0; i < catalogEntries.length; i++) {
            const item = catalogEntries[i];
            const record = metadata[item.file] || null;
            const tags = record && record.tags ? record.tags : [];
            // Bing publishes a different image per market on many days, so a
            // large part of the library only ever had German, Japanese, French
            // and so on. English is preferred for display and search where a
            // translation exists; the original still feeds the haystack so
            // searching in the source language keeps working.
            // Metadata arrives after the catalog on a cold open. Keep the title
            // blank meanwhile rather than briefly exposing the filename.
            const originalTitle = record && record.title ? record.title : "";
            const title = record && record.englishTitle ? record.englishTitle : originalTitle;
            const headline = record && (record.englishHeadline || record.headline) ? record.englishHeadline || record.headline : "";
            const description = record && (record.englishDescription || record.description) ? record.englishDescription || record.description : "";
            const date = record && record.date ? record.date : "";
            entries.push({
                "path": item.path,
                "file": item.file,
                "name": item.name,
                "extension": item.extension,
                "order": i,
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
        for (let i = 0; i < terms.length; i++) {
            const term = terms[i];
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

    // Narrows the list to the query, keeping the current wallpaper selected
    // whenever it survives the filter.
    function applyFilter(preferredPath) {
        const keep = preferredPath !== undefined && preferredPath !== "" ? preferredPath : selectedPath;
        const terms = normalizeText(query).split(" ").filter(term => term !== "");

        // Hidden wallpapers stay in allWallpapers so toggling "is:hidden" is a
        // refilter rather than a rebuild, but only one side is ever reachable.
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

        wallpapers = results;
        const target = results.findIndex(entry => entry.path === keep);
        index = target >= 0 ? target : 0;
    }

    function previewSelected() {
        if (!armed || !visible || selectedPath === "")
            return;
        if (selectedPath === displayedPath) {
            previewTimer.stop();
            return;
        }
        previewTimer.path = selectedPath;
        previewTimer.restart();
    }

    onSelectedPathChanged: previewSelected()

    onVisibleChanged: {
        if (visible)
            search.forceActiveFocus();
        else {
            acceptTimer.stop();
            previewTimer.stop();
            search.text = "";
        }
    }

    HyprlandFocusGrab {
        id: focusGrab
        windows: [overlay]
        onCleared: {
            if (overlay.visible && !FocusGuard.suspended)
                overlay.dismiss();
        }
    }

    Binding {
        target: focusGrab
        property: "active"
        value: overlay.visible && !FocusGuard.suspended
    }

    Process {
        id: catalog
        command: ["wallpaperctl", "catalog"]
        stdout: StdioCollector {
            id: catalogOutput
        }
        onExited: (code, status) => {
            if (code !== 0 || status !== 0)
                return;
            try {
                const result = JSON.parse(catalogOutput.text);
                overlay.catalogEntries = result.wallpapers || [];
                overlay.originalWallpaper = result.current || "";
                overlay.displayedPath = overlay.originalWallpaper;
                overlay.metadataPath = result.metadataFile || "";
                overlay.curationPath = result.curationFile || "";
                // Seeded from the catalog so the first frame already excludes
                // hidden wallpapers, before curation.json has been read.
                const seeded = {};
                for (let i = 0; i < overlay.catalogEntries.length; i++) {
                    const item = overlay.catalogEntries[i];
                    if (item.hidden)
                        seeded[item.file] = true;
                }
                overlay.hiddenFiles = seeded;
                overlay.rebuild();
                if (overlay.metadataPath !== "" && Object.keys(overlay.metadata).length === 0)
                    metadataView.reload();
                Qt.callLater(() => overlay.armed = true);
            } catch (error) {
                console.warn("Cannot load wallpaper catalog:", error);
            }
        }
    }

    FileView {
        id: metadataView
        path: overlay.metadataPath
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: overlay.loadMetadata()
    }

    // printErrors stays off because curation.json legitimately does not exist
    // until the first Ctrl+D.
    FileView {
        id: curationView
        path: overlay.curationPath
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: overlay.loadCuration()
    }

    Timer {
        id: noticeTimer
        interval: 2600
        onTriggered: overlay.notice = ""
    }

    // Debounced because the preview is now the actual wallpaper: holding an arrow
    // key would otherwise hand hyprpaper a decode per keystroke.
    Timer {
        id: previewTimer
        property string path: ""
        interval: 140
        onTriggered: {
            if (!overlay.visible || path === "" || path === overlay.displayedPath)
                return;
            Quickshell.execDetached(["wallpaperctl", "preview", path]);
            overlay.displayedPath = path;
        }
    }

    Item {
        id: stage
        anchors.fill: parent
        opacity: overlay.accepting ? 0 : 1

        Behavior on opacity {
            enabled: overlay.visible
            NumberAnimation {
                duration: 180
                easing.type: Easing.OutCubic
            }
        }

        // Wheel only. Clicks are swallowed rather than acted on, since the whole
        // screen is the hit area and a stray click closing the overlay would be
        // indistinguishable from clicking the desktop.
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            onWheel: wheel => overlay.select(wheel.angleDelta.y < 0 ? 1 : -1)
        }

        // Legibility scrim under the title. Kept shallow so the wallpaper still
        // reads as the wallpaper.
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: parent.height * 0.34
            gradient: Gradient {
                GradientStop {
                    position: 0.0
                    color: "#00000000"
                }
                GradientStop {
                    position: 1.0
                    color: "#99000000"
                }
            }
        }

        // Spotlight: a wide, softly rounded, translucent slab with a leading
        // magnifier and oversized light text. Sits clear of the bar rather than
        // under it.
        Item {
            id: searchRow
            anchors.top: parent.top
            anchors.topMargin: Theme.barHeight + 28
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(720, stage.width * 0.46)
            height: 64
            // The field keeps focus at all times so typing is what reveals it;
            // opacity rather than visibility, so key handling never moves.
            opacity: overlay.rawQuery === "" ? 0 : 1
            scale: overlay.rawQuery === "" ? 0.97 : 1

            Behavior on opacity {
                NumberAnimation {
                    duration: 160
                    easing.type: Easing.OutCubic
                }
            }
            Behavior on scale {
                NumberAnimation {
                    duration: 180
                    easing.type: Easing.OutCubic
                }
            }

            Rectangle {
                id: searchPanel
                anchors.fill: parent
                radius: 18
                color: Qt.rgba(Theme.backgroundBase.r, Theme.backgroundBase.g, Theme.backgroundBase.b, 0.82)
                // Spotlight has no real border, just a hairline highlight that
                // separates the slab from a bright wallpaper.
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.12)

                layer.enabled: true
                layer.effect: MultiEffect {
                    shadowEnabled: true
                    shadowColor: "#b0000000"
                    shadowBlur: 1.0
                    shadowVerticalOffset: 8
                    shadowOpacity: 0.45
                }
            }

            Text {
                id: searchIcon
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                text: "\uf002"
                color: Theme.muted
                font.family: Theme.iconFontFamily
                font.pixelSize: 24
            }

            TextField {
                id: search
                anchors.fill: parent
                anchors.leftMargin: searchIcon.x + searchIcon.width + 16
                focus: true
                placeholderText: "Search wallpapers"
                color: Theme.text
                placeholderTextColor: Theme.muted
                selectionColor: Theme.accentStrong
                selectedTextColor: Theme.backgroundBase
                verticalAlignment: TextInput.AlignVCenter
                background: null
                leftPadding: 0
                topPadding: 0
                bottomPadding: 0
                font.family: Theme.fontFamily
                font.pixelSize: 27
                font.weight: Font.Normal
                font.letterSpacing: -0.3
                rightPadding: resultCount.width + 36
                onTextChanged: filterTimer.restart()

                cursorDelegate: Rectangle {
                    width: 2
                    radius: 1
                    color: Theme.accent
                    visible: search.activeFocus

                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        running: search.activeFocus
                        NumberAnimation {
                            to: 0
                            duration: 520
                            easing.type: Easing.InOutQuad
                        }
                        NumberAnimation {
                            to: 1
                            duration: 520
                            easing.type: Easing.InOutQuad
                        }
                    }
                }

                // Handled here rather than with Shortcut so typing a query never
                // triggers navigation.
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_Left || event.key === Qt.Key_Up) {
                        overlay.select(-1);
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Right || event.key === Qt.Key_Down) {
                        overlay.select(1);
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Escape) {
                        if (search.text !== "")
                            search.text = "";
                        else
                            overlay.applySelected();
                        event.accepted = true;
                    } else if (event.key === Qt.Key_Backspace && search.text === "") {
                        overlay.restoreOriginal();
                        event.accepted = true;
                    } else if (event.key === Qt.Key_R && (event.modifiers & Qt.ControlModifier)) {
                        overlay.selectRandom();
                        event.accepted = true;
                    } else if (event.key === Qt.Key_D && (event.modifiers & Qt.ControlModifier)) {
                        overlay.toggleHiddenSelected();
                        event.accepted = true;
                    }
                }
                onAccepted: {
                    if (search.text === "")
                        overlay.applySelected();
                    else {
                        overlay.accepting = true;
                        acceptTimer.restart();
                    }
                }
            }

            Text {
                id: resultCount
                anchors.right: parent.right
                anchors.rightMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                visible: overlay.filtering
                text: overlay.wallpapers.length + "/" + overlay.poolSize + (overlay.showingHidden ? " hidden" : "")
                color: overlay.wallpapers.length === 0 ? Theme.danger : Theme.muted
                font.family: Theme.fontFamily
                font.pixelSize: 14
            }
        }

        Timer {
            id: filterTimer
            interval: 90
            onTriggered: overlay.applyFilter()
        }

        Timer {
            id: acceptTimer
            interval: 180
            onTriggered: overlay.applySelected()
        }

        Column {
            id: caption
            anchors.left: parent.left
            anchors.leftMargin: overlay.edgeMargin
            anchors.bottom: parent.bottom
            anchors.bottomMargin: overlay.bottomMargin
            width: Math.min(stage.width - overlay.edgeMargin * 2, stage.width * 0.66)
            spacing: 6

            Text {
                id: captionTitle
                width: parent.width
                elide: Text.ElideRight
                text: overlay.wallpapers.length === 0 ? (overlay.showingHidden && overlay.query === "" ? "Nothing is hidden" : overlay.filtering ? "No matches" : catalog.running ? "Loading wallpapers" : "No wallpapers in ~/Wallpapers") : overlay.armed && overlay.selected ? overlay.selected.title : ""
                color: "#ffffff"
                font.family: Theme.fontFamily
                font.pixelSize: overlay.titleSize
                font.weight: overlay.titleWeight
                font.letterSpacing: -0.4

                layer.enabled: true
                layer.effect: MultiEffect {
                    shadowEnabled: true
                    shadowColor: "#c0000000"
                    shadowBlur: 0.7
                    shadowVerticalOffset: 2
                    shadowOpacity: 0.55
                }
            }

            Text {
                width: parent.width
                elide: Text.ElideRight
                visible: text !== ""
                // The transient Ctrl+D confirmation lives here; a separate popup
                // would break the overlay's focus grab.
                text: overlay.notice
                color: Theme.accent
                font.family: Theme.fontFamily
                font.pixelSize: 16
                font.weight: Font.Medium
            }
        }
    }
}
