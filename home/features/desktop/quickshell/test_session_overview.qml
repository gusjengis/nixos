import QtQuick
import Quickshell
import "config/SessionOverview.js" as Overview

ShellRoot {
    function check(value, message) {
        if (!value) throw new Error(message);
    }
    Timer {
        running: true
        interval: 10
        onTriggered: {
            try {
                const monitors = [{ id: 0, name: "DP-1", x: 100, y: 0, width: 3840, height: 2160, scale: 2 },
                    { id: 1, name: "DP-2", x: 2020, y: 0, width: 1920, height: 1080, scale: 1 }];
                const windows = [
                    { address: "a", mapped: true, workspace: { address: "slot-a" }, monitor: 0, focusHistoryID: 5 },
                    { address: "b", mapped: true, workspace: { address: "special:notes" }, monitor: 0, focusHistoryID: 0 },
                    { address: "c", mapped: true, workspace: { address: "special:notes" }, monitor: 0, focusHistoryID: 2 },
                    { address: "global", mapped: true, workspace: { address: "special:music" }, monitor: 0, focusHistoryID: 1 },
                    { address: "foreign", mapped: true, workspace: { address: "slot-other" }, monitor: 0, focusHistoryID: 3 },
                    { address: "dead", mapped: false, workspace: { address: "slot-a" }, monitor: 0, focusHistoryID: 4 },
                    { address: "d", mapped: true, workspace: { address: "special:notes" }, monitor: 1, focusHistoryID: 7 }
                ];
                const result = Overview.overview({ windows: ["a", "b", "c", "d", "dead"],
                    workspaces: { "DP-1": ["slot-a"] }, slots: { "DP-1": 1 },
                    visible_specials: { "DP-1": "notes" }, specials: { notes: "special:notes" } }, windows, monitors);
                check(result.windows.length === 4, "Exclude global, foreign and unmapped windows");
                check(result.groups.length === 3, "Separate occupied workspaces and monitors");
                check(result.groups[0].label === "Notes" && result.groups[0].current, "Prefer visible scratchpad");
                check(result.groups[0].backgroundWindows[0].address === "a", "Special overlays remembered normal workspace");
                check(result.groups[0].windows[1].address === "b", "Paint focused window last");
                check(result.groups[0].width === 1920 && result.groups[0].x === 100, "Use logical monitor geometry");
                check(result.groups[1].label === "Workspace 1", "Registry labels numbered slots");
                check(result.groups[2].monitor === "DP-2", "Retain second monitor label");
                check(Overview.overview({ windows: {} }, windows, []).groups.length === 0, "Empty Lua table is empty session");
                check(Overview.overview({ windows: ["a"] }, windows, []).groups[0].width > 0, "Disconnected monitor has usable fallback");
                const hidden = Overview.overview({ windows: ["a", "b", "c"],
                    workspaces: { "DP-1": ["slot-a", "empty"] }, slots: { "DP-1": 2 },
                    visible_specials: {}, specials: { notes: "special:notes" } }, windows, monitors);
                check(hidden.groups[0].name === "empty" && hidden.groups[0].current, "Empty selected workspace beats focused special");
                check(hidden.groups[0].windows.length === 0, "Hidden special cannot leak onto empty desktop");
                const layered = Overview.overview({ windows: ["a", "b", "c"],
                    workspaces: { "DP-1": ["slot-a", "empty"] }, slots: { "DP-1": 2 },
                    visible_specials: { "DP-1": "notes" }, specials: { notes: "special:notes" } }, windows, monitors);
                check(layered.groups[0].name === "special:notes" && layered.groups[0].backgroundWindows.length === 0,
                    "Overlay uses selected empty normal workspace, not old focused fullscreen app");
                console.log("PASS: ownership, current/empty workspace selection, layered scratchpads, focus order, scaling and labels");
                Qt.quit();
            } catch (error) {
                console.error("FAILED:", error);
                Qt.exit(1);
            }
        }
    }
}
