import QtQuick
import QtQml.Models
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import "state"
import "DockState.js" as DockState

// Apps of the active desktop session, one entry per window class, in the order
// they first appeared (macOS appends newly launched apps). `items` is the Dock:
// Strata (Finder) first, then pinned/running apps in the context's chosen order.
// Local pin/unpin overrides and order live in .context/state/dock.json;
// effective pins follow current logical ancestry, including live reparenting.
Scope {
    id: root

    property var apps: []
    property var items: []
    readonly property string finderId: "io.github.lgse.Strata"
    // Saved contexts own a folder; unsaved runtime sessions have no pins.
    property string contextPath: ((DesktopSessions.contextCatalog.nodes || [])
        .find(node => node.runtime_id && node.runtime_id === DesktopSessions.active) || {}).path || ""
    property string runtimeSession: DesktopSessions.active
    property var runtimeOrders: ({})
    property var contextNodes: DesktopSessions.contextCatalog.nodes || []
    readonly property var activeContext: contextNodes.find(node => node.path === contextPath) || null
    readonly property bool hasSeparateSessionFolder: !!activeContext && !!contextPath
        && !!activeContext.working_directory_path && activeContext.working_directory_path !== contextPath
    readonly property var ancestry: DockState.ancestry(contextNodes, contextPath)
    property var pinStates: ({})
    readonly property var effectiveState: DockState.resolve(ancestry, pinStates, finderId)
    readonly property var localState: DockState.normalize(pinStates[contextPath] || {}, finderId)
    readonly property string pinFile: contextPath ? contextPath + "/.context/state/dock.json" : ""
    readonly property var pinned: effectiveState.pinned
    readonly property var order: pinFile ? effectiveState.order : (runtimeOrders[runtimeSession] || [])
    onOrderChanged: rebuildItems()
    onPinnedChanged: rebuildItems()
    onAppsChanged: rebuildItems()
    property var firstSeen: ({})
    property int sequence: 0
    property var toplevels: Hyprland.toplevels.values
    // Track metadata as well as list membership. IPC metadata can arrive well
    // after the Wayland toplevel and the session ownership snapshot.
    readonly property var windowStates: toplevels.map(toplevel => toplevel.lastIpcObject)
    property var generatedIcons: ({})
    property var nativeIcons: ({})
    property var applications: DesktopEntries.applications.values
    // Proton windows whose class names no desktop entry: the entry that
    // launched their process (pid -> id, "" when unknown) and Steam's own
    // library metadata (app ID -> { name, icon }).
    property var launchedEntries: ({})
    property var steamGames: ({})
    property var pendingPids: []
    property var pendingSteam: []
    readonly property string iconThemePath: (Quickshell.env("XDG_DATA_HOME") || Quickshell.env("HOME") + "/.local/share") + "/icons/MacOS-Native"

    // An empty Lua table arrives as {} rather than [].
    property var sessionWindows: {
        const windows = (DesktopSessions.sessions.find(session => session.id === DesktopSessions.active) || {}).windows;
        return Array.isArray(windows) ? windows : [];
    }

    onSessionWindowsChanged: rebuild()
    onWindowStatesChanged: rebuild()
    onGeneratedIconsChanged: rebuild()
    onNativeIconsChanged: rebuild()
    onApplicationsChanged: rebuild()
    onLaunchedEntriesChanged: rebuild()
    onSteamGamesChanged: rebuild()
    Component.onCompleted: { Hyprland.refreshToplevels(); rebuild(); }

    Connections {
        target: Hyprland
        function onRawEvent(event) {
            if (["openwindow", "closewindow", "activewindowv2", "movewindowv2", "windowtitlev2"].includes(event.name))
                Hyprland.refreshToplevels();
        }
    }
    FileView {
        path: root.iconThemePath + "/generated-apps.json"
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                const icons = {};
                for (const entry of JSON.parse(text()))
                    icons[entry.icon] = entry.fingerprint;
                root.generatedIcons = icons;
            } catch (error) {
                console.warn("Cannot read generated dock icons:", error.message);
            }
        }
    }

    FileView {
        path: root.iconThemePath + "/linux-mappings.json"
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                const icons = {};
                for (const entry of JSON.parse(text()))
                    for (const alias of entry.aliases || [])
                        if (alias.startsWith("apps/"))
                            icons[alias.slice(5)] = true;
                root.nativeIcons = icons;
            } catch (error) {
                console.warn("Cannot read native dock icons:", error.message);
            }
        }
    }

    function appKey(cls, title) {
        if (cls.startsWith("context-terminal-"))
            return "kitty";
        // Every RDP launcher starts the same client. Resolve its shared window
        // identity to the Windows launcher, regardless of the remote host.
        if (cls === "xfreerdp")
            return "windows-vm";
        // Proton gives launchers and games the same Steam shortcut class.
        // Keep Battle.net distinct from the game that started it.
        if (/^steam_app_\d+$/.test(cls) && /^Battle\.net(?:$|\s|\s*[-—])/.test(title || ""))
            return "battle-net";
        return cls;
    }

    function steamWindowId(exec) {
        const launch = /steam:\/\/(?:rungameid|run)\/(\d+)(?=$|[\s/"'])/.exec(exec || "");
        if (!launch)
            return "";
        const id = launch[1];
        if (Number(id) <= 0xffffffff)
            return String(Number(id));
        // Non-Steam shortcuts launch with a 64-bit game ID, but WM_CLASS
        // contains its high 32 bits. Divide decimal digits to avoid rounding
        // the original ID through JavaScript's 53-bit integer precision.
        let high = 0;
        let remainder = 0;
        for (const digit of id) {
            remainder = remainder * 10 + Number(digit);
            high = high * 10 + Math.floor(remainder / 0x100000000);
            remainder %= 0x100000000;
        }
        return String(high);
    }

    function steamEntry(id) {
        return applications.find(app => steamWindowId(app.execString) === id);
    }

    function describe(key) {
        if (key.startsWith("entry:")) {
            const item = entryItem(key.slice(6));
            if (item) return { entryId: item.entryId, name: item.name, icon: item.icon };
        }
        const steam = /^steam_app_(\d+)$/.exec(key);
        if (steam) {
            const entry = steamEntry(steam[1]);
            const game = steamGames[steam[1]] || {};
            return {
                entryId: entry ? entry.id : "",
                name: entry ? entry.name : (game.name || "Steam Game"),
                icon: (entry && entry.icon ? iconPath(entry.icon) : "")
                    || iconPath("steam_icon_" + steam[1]) || game.icon || iconPath("steam")
            };
        }
        const entry = DesktopEntries.heuristicLookup(key);
        const icon = (entry && entry.icon ? iconPath(entry.icon) : "")
            || iconPath(key) || iconPath(key.toLowerCase())
            || Quickshell.iconPath("application-x-executable");
        return { entryId: entry ? entry.id : "", name: entry && entry.name ? entry.name : key, icon: icon };
    }

    Instantiator {
        model: root.ancestry
        delegate: FileView {
            id: inheritedStore
            required property string modelData
            property bool missing: true
            // QFileSystemWatcher cannot watch a file whose parent directories
            // do not exist yet. Retry only absent state; existing files use events.
            property Timer retry: Timer {
                interval: 1000
                running: inheritedStore.missing
                repeat: true
                onTriggered: inheritedStore.reload()
            }
            path: modelData + "/.context/state/dock.json"
            preload: true
            watchChanges: true
            printErrors: false
            onFileChanged: reload()
            onLoaded: {
                missing = false;
                try {
                    root.updatePinState(modelData, JSON.parse(text()));
                } catch (error) {
                    console.warn("Cannot read dock pins:", error.message);
                    root.updatePinState(modelData, {});
                }
            }
            onLoadFailed: { missing = true; root.updatePinState(modelData, {}); }
        }
    }

    function updatePinState(path, state) {
        pinStates = Object.assign({}, pinStates, { [path]: DockState.normalize(state, finderId) });
    }

    // Immutable, serialized snapshots: a context switch during mkdir/write
    // must not redirect the previous context's order into the new one.
    property var pendingWrites: []
    Process {
        id: pinWriter
        onExited: code => {
            if (code !== 0) console.warn("Cannot save dock state");
            Qt.callLater(root.writeNextState);
        }
    }

    function canPin(app) { return !!pinFile && !!app.entryId && app.entryId !== finderId; }
    function orderKey(app) { return app.entryId ? "entry:" + app.entryId : app.key; }

    // Reordering never pins a running app. Keep Finder fixed, but allow all
    // other tiles to cross one another without a pinned/running boundary.
    function reorder(key, target) {
        const next = items.slice();
        const from = next.findIndex(app => orderKey(app) === key);
        if (from < 0 || next[from].permanent || next.length < 2) return;
        target = Math.max(next[0].permanent ? 1 : 0, Math.min(next.length - 1, target));
        if (from === target) return;
        next.splice(target, 0, next.splice(from, 1)[0]);
        const nextOrder = next.filter(app => !app.permanent).map(orderKey);
        if (!pinFile) runtimeOrders = Object.assign({}, runtimeOrders, { [runtimeSession]: nextOrder });
        else saveState(Object.assign({}, localState, { order: nextOrder }));
    }

    function saveState(state) {
        if (!pinFile) return;
        updatePinState(contextPath, state);
        pendingWrites = pendingWrites.filter(write => write.path !== pinFile).concat([{
            path: pinFile,
            payload: JSON.stringify(localState, null, 2) + "\n"
        }]);
        writeNextState();
    }

    function writeNextState() {
        if (pinWriter.running || !pendingWrites.length) return;
        const write = pendingWrites[0];
        pendingWrites = pendingWrites.slice(1);
        // Arguments, not shell interpolation; atomically publish complete JSON
        // so every screen's FileView sees either the old or the new snapshot.
        pinWriter.command = ["sh", "-c",
            'mkdir -p -- "$1" && tmp=$(mktemp "$2.XXXXXX") && trap \'rm -f -- "$tmp"\' EXIT && printf "%s" "$3" > "$tmp" && mv -f -- "$tmp" "$2"',
            "dock-state", write.path.slice(0, write.path.lastIndexOf("/")), write.path, write.payload];
        pinWriter.running = true;
    }

    function setPinned(app, keep) {
        if (!canPin(app)) return;
        const next = localState.pinned.filter(id => id !== app.entryId);
        const removed = localState.removed.filter(id => id !== app.entryId);
        if (keep) {
            // macOS keeps a newly pinned app where it currently sits.
            const index = items.indexOf(app);
            const before = items.slice(0, Math.max(0, index)).filter(item => item.pinned && !item.permanent).length;
            next.splice(before, 0, app.entryId);
        } else removed.push(app.entryId);
        saveState(Object.assign({}, localState, { pinned: next, removed: removed }));
    }

    function entryItem(id) {
        const entry = DesktopEntries.byId(id);
        if (!entry) return null;
        return { key: "entry:" + id, entryId: id, name: entry.name,
            icon: (entry.icon ? iconPath(entry.icon) : "") || iconPath(id) || Quickshell.iconPath("application-x-executable"),
            windows: [], cycle: [] };
    }

    function rebuildItems() {
        const running = apps.slice();
        const result = [];
        for (const id of [finderId].concat(pinned)) {
            if (result.some(item => item.entryId === id)) continue;
            const index = running.findIndex(app => app.entryId === id);
            const base = index >= 0 ? running.splice(index, 1)[0] : entryItem(id);
            if (base) result.push(Object.assign({}, base, { pinned: true, permanent: id === finderId, running: index >= 0 }));
        }
        for (const app of running)
            result.push(Object.assign({}, app, { pinned: false, permanent: false, running: true }));
        const fallback = result.slice();
        result.sort((a, b) => {
            if (a.permanent || b.permanent) return Number(b.permanent) - Number(a.permanent);
            const ai = order.indexOf(orderKey(a));
            const bi = order.indexOf(orderKey(b));
            return (ai < 0 ? order.length + fallback.indexOf(a) : ai)
                - (bi < 0 ? order.length + fallback.indexOf(b) : bi);
        });
        items = result;
    }

    function iconPath(name) {
        const fingerprint = generatedIcons[name];
        // QIcon's provider caches both theme lookup and pixels. The manifest is
        // published after all sizes, so a new fingerprint safely reloads art.
        // Native small-size variants have different silhouettes/highlights.
        // Always fit the complete large artwork instead of selecting those
        // variants at the tile's small decode size.
        if (fingerprint || nativeIcons[name])
            return "file://" + iconThemePath + "/512x512/apps/" + encodeURIComponent(name) + ".png"
                + (fingerprint ? "?v=" + fingerprint : "");
        return Quickshell.iconPath(name, true);
    }

    // A Proton class only names a game when a Steam launcher matches its ID.
    // Otherwise prefer the desktop entry that started the window's process,
    // so games launched outside Steam (class steam_app_0) get distinct tiles.
    function windowKey(state) {
        const key = appKey(state.initialClass || state.class || "", state.title);
        const steam = /^steam_app_(\d+)$/.exec(key);
        if (!steam || steamEntry(steam[1]))
            return key;
        const pid = state.pid > 0 ? String(state.pid) : "";
        const launched = pid ? launchedEntries[pid] : "";
        if (launched === undefined)
            requestIdentity(pendingPids, pid);
        else if (launched && DesktopEntries.byId(launched))
            return "entry:" + launched;
        if (steam[1] !== "0" && steamGames[steam[1]] === undefined)
            requestIdentity(pendingSteam, steam[1]);
        return key;
    }

    function requestIdentity(queue, value) {
        if (queue.includes(value) || identityReader.pids.includes(value) || identityReader.steam.includes(value))
            return;
        queue.push(value);
        Qt.callLater(lookUpIdentities);
    }

    function lookUpIdentities() {
        if (identityReader.running || (!pendingPids.length && !pendingSteam.length))
            return;
        identityReader.pids = pendingPids;
        identityReader.steam = pendingSteam;
        pendingPids = [];
        pendingSteam = [];
        identityReader.command = [Quickshell.env("HOME") + "/.nix-profile/bin/quickshell-dock-identity"]
            .concat(...identityReader.pids.map(pid => ["--pid", pid]))
            .concat(...identityReader.steam.map(id => ["--steam", id]));
        identityReader.running = true;
    }

    Process {
        id: identityReader
        property var pids: []
        property var steam: []
        stdout: StdioCollector { id: identityOutput }
        onExited: code => {
            let result = {};
            try {
                if (code === 0) result = JSON.parse(identityOutput.text);
            } catch (error) {
                console.warn("Cannot identify dock windows:", error.message);
            }
            // Record failures too, so a window is only inspected once. Drop
            // exited processes so a reused pid is inspected afresh.
            const live = root.windowStates.filter(state => state && state.pid > 0).map(state => String(state.pid));
            const entries = {};
            for (const pid of Object.keys(root.launchedEntries).concat(pids))
                if (live.includes(pid))
                    entries[pid] = ((result.pids || {})[pid] ?? root.launchedEntries[pid]) || "";
            const games = Object.assign({}, root.steamGames);
            for (const id of steam)
                games[id] = (result.steam || {})[id] || {};
            pids = [];
            steam = [];
            root.launchedEntries = entries;
            root.steamGames = games;
            Qt.callLater(root.lookUpIdentities);
        }
    }

    function rebuild() {
        const groups = {};
        const order = [];
        for (const state of windowStates) {
            if (!state || !state.address || !sessionWindows.includes(state.address))
                continue;
            const key = windowKey(state);
            if (key === "")
                continue;
            if (!groups[key]) {
                groups[key] = { key: key, windows: [] };
                order.push(key);
            }
            groups[key].windows.push({ address: state.address, focus: state.focusHistoryID });
        }
        const seen = Object.assign({}, firstSeen);
        for (const key of order)
            if (seen[key] === undefined)
                seen[key] = sequence++;
        firstSeen = seen;
        order.sort((a, b) => seen[a] - seen[b]);
        apps = order.map(key => {
            const group = groups[key];
            group.windows.sort((a, b) => a.focus - b.focus);
            const windows = group.windows.map(window => window.address);
            return Object.assign(describe(key), { key: key, windows: windows, cycle: windows.slice().sort() });
        });
    }

    // Raise the app's most recent window; when it is already focused, cycle.
    function activate(app) {
        if (app.entryId === finderId) {
            launch(app);
            return;
        }
        if (!app.windows.length) {
            launch(app);
            return;
        }
        const active = Hyprland.activeToplevel ? "0x" + Hyprland.activeToplevel.address : "";
        const current = app.cycle.indexOf(active);
        const target = current < 0 ? app.windows[0] : app.cycle[(current + 1) % app.cycle.length];
        Quickshell.execDetached(["hyprctl", "eval", "require('sessions').focus_window('address:" + target + "', { preserve_cursor = true })"]);
    }

    function launch(app) {
        // Follow profile updates even when this shell inherited an old store path.
        if (app.entryId === finderId) {
            openFiles(false);
            return;
        }
        const entry = app.entryId ? DesktopEntries.byId(app.entryId) : null;
        if (!entry) return;
        if (entry.runInTerminal || !entry.command.length) {
            entry.execute();
            return;
        }
        // Mark the process like GLib launchers do, for windows whose class
        // does not identify their entry. Quickshell exposes IDs, not paths.
        const context = { command: entry.command, environment: { GIO_LAUNCHED_DESKTOP_FILE: entry.id + ".desktop" } };
        if (entry.workingDirectory) context.workingDirectory = entry.workingDirectory;
        Quickshell.execDetached(context);
    }

    function filesCommand(sessionDirectory) {
        const command = [Quickshell.env("HOME") + "/.nix-profile/bin/contextctl", "files"];
        if (runtimeSession) command.push("--runtime", runtimeSession);
        if (sessionDirectory) command.push("--session-directory");
        return command;
    }

    function openFiles(sessionDirectory) {
        Quickshell.execDetached(filesCommand(sessionDirectory));
    }
}
