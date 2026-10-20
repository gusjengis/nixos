pragma Singleton

import QtQuick
import Quickshell
import Quickshell.Io

QtObject {
    id: root

    readonly property bool available: !!Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") && !!Quickshell.env("XDG_RUNTIME_DIR")
    property var snapshot: ({})
    readonly property var sessions: snapshot.sessions || []
    property var contextCatalog: ({ contexts: [] })
    readonly property var openSessions: sessions.map(session => Object.assign({}, session, { runtime_id: session.id, persistent: false }))
    readonly property var savedContexts: (contextCatalog.contexts || []).map(context => Object.assign({}, context, { persistent: true }))
    readonly property string active: snapshot.active || ""
    readonly property string activeName: (sessions.find(session => session.id === active) || {}).name || "Sessions"
    readonly property bool busy: request.running
    property string error: ""
    property string pendingAction: ""
    signal completed(string action)
    signal failed()

    // Lua decimal escapes are fixed-width: following digits cannot extend them.
    function luaString(value) {
        return '"' + String(value).replace(/[\\"\x00-\x1f\x7f]/g, character => {
            if (character === '"' || character === '\\')
                return '\\' + character;
            return '\\' + ("000" + character.charCodeAt(0)).slice(-3);
        }) + '"';
    }

    function workspaceName(slot, monitorName) {
        return ((snapshot.workspaces || {})[monitorName] || [])[slot - 1] || "";
    }

    function specialName(role) {
        return (snapshot.specials || {})[role] || "";
    }

    function report(message) {
        error = message;
        failed();
    }

    function run(action, args) {
        if (busy)
            return false;
        if (!available) {
            report("Sessions require a live Hyprland session.");
            return false;
        }
        error = "";
        pendingAction = action;
        request.didStart = false;
        request.command = ["hyprctl", "eval", "return require('sessions')." + action + "(" + args.join(",") + ")"];
        request.running = true;
        return true;
    }

    function contextCommand(action, args) {
        if (busy)
            return false;
        if (!available) {
            report("Sessions require a live Hyprland session.");
            return false;
        }
        error = "";
        pendingAction = action;
        request.didStart = false;
        request.command = ["contextctl"].concat(args);
        request.running = true;
        return true;
    }

    function switchSession(id) {
        return (contextCatalog.contexts || []).some(context => context.id === id)
            ? contextCommand("open", ["open", id]) : run("switch", [luaString(id)]);
    }
    function closeSession(id) { return contextCommand("close", ["close", "--runtime", id]); }
    function previous() { return run("previous", []); }
    function selectWorkspace(slot, monitorName) { return run("select_workspace", [String(slot), luaString(monitorName)]); }
    function toggleSpecial(role, monitorName) { return run("toggle_special", [luaString(role), luaString(monitorName)]); }

    function saveName(action, id, name) {
        if (!name.trim() || /[\x00-\x1f\x7f-\x9f]/.test(name)) {
            report("Use a non-empty name without control characters.");
            return false;
        }
        name = name.trim();
        return run(action, action === "rename" ? [luaString(id), luaString(name)] : [luaString(name)]);
    }

    function create(name) { return contextCommand("create", ["create", name.trim(), "--open"]); }
    function rename(id, name) {
        return (contextCatalog.contexts || []).some(context => context.id === id)
            ? contextCommand("rename", ["rename", id, name.trim()]) : saveName("rename", id, name);
    }

    property var contextFile: FileView {
        path: root.available ? Quickshell.env("XDG_RUNTIME_DIR") + "/desktop-contexts-" + Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") + ".json" : ""
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                const value = JSON.parse(text());
                if (!Array.isArray(value.contexts))
                    throw new Error("Invalid context catalog");
                root.contextCatalog = value;
            } catch (error) {
                root.report("Cannot read contexts: " + error.message);
            }
        }
    }

    property var stateFile: FileView {
        path: root.available ? Quickshell.env("XDG_RUNTIME_DIR") + "/hyprland-sessions-" + Quickshell.env("HYPRLAND_INSTANCE_SIGNATURE") + ".json" : ""
        preload: true
        watchChanges: true
        printErrors: false
        onFileChanged: reload()
        onLoaded: {
            try {
                const value = JSON.parse(text());
                if (!Array.isArray(value.sessions) || typeof value.active !== "string")
                    throw new Error("Invalid session snapshot");
                root.snapshot = value;
            } catch (error) {
                root.report("Cannot read sessions: " + error.message);
            }
        }
    }

    property var request: Process {
        id: request
        property bool didStart: false
        onStarted: didStart = true
        onRunningChanged: {
            if (!running && !didStart) {
                Qt.callLater(() => root.report("Cannot start hyprctl. Check that it is installed and available in PATH."));
            }
        }
        stdout: StdioCollector { id: output }
        stderr: StdioCollector { id: errors }
        onExited: (code, status) => {
            const stdout = output.text.trim();
            const stderr = errors.text.trim();
            root.stateFile.reload();
            root.contextFile.reload();
            // Eval reports errors on stdout even with exit status zero.
            if (code !== 0 || status !== 0 || stdout !== "ok") {
                root.report(stderr || (stdout !== "ok" ? stdout : "") || "Session command failed (" + code + ").");
            } else {
                root.completed(root.pendingAction);
            }
        }
    }
}
