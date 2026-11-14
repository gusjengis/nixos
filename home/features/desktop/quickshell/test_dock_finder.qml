import QtQuick
import Quickshell
import "config" as Desktop

ShellRoot {
    Desktop.DockModel {
        id: dock
        contextPath: "/sessions/Example"
        runtimeSession: "s-test"
        contextNodes: [{path: "/sessions/Example", working_directory_path: "/work/project"}]
        toplevels: []
        sessionWindows: []
        property var opened: []
        function openFiles(sessionDirectory) { opened = opened.concat([sessionDirectory]); }
    }
    Desktop.DockMenu { id: menu; dockModel: dock }
    function check(value, message) {
        if (!value) throw new Error(message);
    }
    Timer {
        interval: 100; running: true
        onTriggered: {
            try {
                const finder = {entryId: dock.finderId, name: "Finder", permanent: true,
                    running: false, windows: [], cycle: []};
                check(dock.filesCommand(false).join("|") === Quickshell.env("HOME")
                    + "/.nix-profile/bin/contextctl|files|--runtime|s-test", "Finder uses shortcut command with originating runtime");
                check(dock.filesCommand(true).slice(-1)[0] === "--session-directory", "Session folder flag");
                dock.activate(finder);
                finder.running = true;
                finder.windows = ["0xfinder"];
                finder.cycle = finder.windows;
                dock.activate(finder);
                dock.launch(finder);
                check(JSON.stringify(dock.opened) === "[false,false,false]", "Cold, running and menu launches all open working directory");
                for (const running of [false, true]) {
                    finder.running = running;
                    check(menu.appEntries(finder).some(e => e.text === "Open Desktop Folder"), "Different folders offer action, running=" + running);
                }
                const editor = {entryId: "", name: "Editor", running: false, windows: []};
                check(!menu.appEntries(editor).some(e => e.text === "Open Desktop Folder"), "Other apps unchanged");
                dock.contextNodes = [{path: dock.contextPath, working_directory_path: dock.contextPath}];
                check(!dock.hasSeparateSessionFolder, "Same directory");
                check(!menu.appEntries(finder).some(e => e.text === "Open Desktop Folder"), "Same folder hides action");
                dock.contextNodes = [{path: dock.contextPath, working_directory_path: "/offline", working_directory_available: false}];
                check(dock.hasSeparateSessionFolder, "Offline working directory still allows session folder");
                dock.contextPath = "";
                dock.runtimeSession = "";
                check(!dock.hasSeparateSessionFolder, "Unsaved context has no separate folder");
                check(dock.filesCommand(false).length === 2, "No runtime preserves shortcut fallback");
                console.log("PASS: Finder dock uses context files; conditional session folder action");
            } catch (error) {
                console.error("FAIL:", error.message);
            }
            Qt.quit();
        }
    }
}
