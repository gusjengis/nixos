import QtQuick
import Quickshell
import "config" as Desktop

ShellRoot {
    id: root
    property int stage: 0
    QtObject { id: first; property var lastIpcObject: ({}) }
    QtObject { id: second; property var lastIpcObject: ({}) }
    Desktop.DockModel {
        id: dock
        toplevels: [first, second]
        sessionWindows: ["0xfirst", "0xsecond"]
    }
    Image {
        id: icon
        source: dock.apps.length ? dock.apps[0].icon : ""
        sourceSize: Qt.size(64, 64)
        asynchronous: true
    }
    function check(value, message) {
        if (!value) throw new Error(message);
    }
    Timer {
        interval: 300; running: true; repeat: true
        onTriggered: {
            try {
                if (root.stage === 0) {
                    root.check(dock.apps.length === 0, "No metadata must not create phantom apps");
                    // Arrives after the old 120 ms settle timer, without a
                    // toplevel-list or session-list membership change.
                    first.lastIpcObject = { address: "0xfirst", class: "webapp-google-messages", focusHistoryID: 1 };
                    root.check(dock.apps.length === 1, "Late IPC metadata must immediately add app");
                    root.check(dock.apps[0].icon.startsWith("file://") && dock.apps[0].icon.includes(".png?v="), "Generated art must bypass cached theme provider");
                    root.stage = 1;
                } else if (root.stage === 1) {
                    root.check(dock.nativeIcons.obsidian === true, "Imported native artwork must be indexed");
                    root.check(dock.iconPath("obsidian").endsWith("/512x512/apps/obsidian.png"), "Native icons must fit complete large artwork, not small-size variants");
                    root.check(dock.apps[0].icon.includes("/512x512/apps/"), "Generated icons must also use full-resolution artwork");
                    root.check(icon.status === Image.Ready, "Fingerprint URL must load actual squircle pixels");
                    root.check(icon.sourceSize.width === 64, "Icon image loaded at requested size");
                    second.lastIpcObject = { address: "0xsecond", class: "webapp-google-messages", focusHistoryID: 0 };
                    root.check(dock.apps.length === 1 && dock.apps[0].windows.length === 2, "Same app groups windows");
                    root.check(dock.apps[0].windows[0] === "0xsecond", "Metadata updates focus order");
                    const oldIcon = dock.apps[0].icon;
                    dock.generatedIcons = Object.assign({}, dock.generatedIcons, { "webapp-google-messages": "test-new-fingerprint" });
                    root.check(dock.apps[0].icon !== oldIcon && dock.apps[0].icon.endsWith("test-new-fingerprint"), "New artwork must invalidate image URL");
                    dock.sessionWindows = ["0xsecond"];
                    root.check(dock.apps[0].windows.length === 1, "Session ownership filters windows");
                    second.lastIpcObject = {};
                    root.check(dock.apps.length === 0, "Closed metadata removes app immediately");
                    // Fixtures exercise matching independently of installed games
                    // and use a real themed icon to check the complete image path.
                    dock.applications = [
                        { name: "Wrong prefix", execString: "steam steam://rungameid/23575700", icon: "steam" },
                        { name: "Native game", execString: "steam steam://rungameid/2357570", icon: "webapp-google-messages" },
                        { name: "Shortcut", execString: "steam steam://rungameid/11862093187843620864", icon: "webapp-google-messages" }
                    ];
                    root.check(dock.steamWindowId("steam steam://run/2357570//") === "2357570", "Steam run URI must match too");
                    root.check(dock.steamWindowId("steam steam://rungameid/2357570oops") === "", "Malformed IDs must not match");
                    root.check(dock.steamWindowId("steam steam://rungameid/18446744073709551615") === "4294967295", "64-bit ID division must be exact");
                    root.check(dock.describe("steam_app_2357570").name === "Native game", "App IDs must match exactly, not by prefix");
                    root.check(dock.describe("steam_app_2357570").icon === dock.iconPath("webapp-google-messages"), "Native game must use launcher's custom artwork");
                    second.lastIpcObject = { address: "0xsecond", initialClass: "steam_app_2761858792", class: "steam_app_2761858792", focusHistoryID: 0 };
                    root.check(dock.apps[0].name === "Shortcut", "Shortcut launch ID must match window's high 32 bits");
                    root.check(dock.apps[0].icon === dock.iconPath("webapp-google-messages"), "Shortcut must use launcher's custom artwork");
                    root.check(dock.describe("steam_app_42").icon === (dock.iconPath("steam_icon_42") || dock.iconPath("steam")), "Missing launcher must retain icon fallback");
                    dock.applications = [{ name: "Updated shortcut", execString: "steam steam://rungameid/11862093187843620864", icon: "steam" }];
                    root.check(dock.apps[0].name === "Updated shortcut" && dock.apps[0].icon === dock.iconPath("steam"), "Desktop entry updates must refresh running game");
                    dock.applications = [{ name: "Shortcut", execString: "steam steam://rungameid/11862093187843620864", icon: "webapp-google-messages" }];
                    root.stage = 2;
                } else if (root.stage === 2) {
                    root.check(icon.status === Image.Ready, "Resolved Steam launcher artwork must load actual pixels");
                    dock.sessionWindows = ["0xfirst", "0xsecond"];
                    first.lastIpcObject = { address: "0xfirst", initialClass: "steam_app_2761858792", title: "Battle.net", focusHistoryID: 1 };
                    second.lastIpcObject = { address: "0xsecond", initialClass: "steam_app_2761858792", title: "World of Warcraft", focusHistoryID: 0 };
                    root.check(dock.apps.length === 2, "Battle.net and its game must have separate dock tiles despite shared Steam class");
                    root.check(dock.apps.some(app => app.key === "battle-net" && app.name === "Battle.net"), "Battle.net must resolve its own desktop entry");
                     root.check(dock.apps.some(app => app.key === "steam_app_2761858792" && app.name === "Shortcut"), "Game must retain shortcut identity");
                     first.lastIpcObject = { address: "0xfirst", initialClass: "xfreerdp", title: "FreeRDP: first-host", focusHistoryID: 1 };
                     second.lastIpcObject = { address: "0xsecond", initialClass: "xfreerdp", title: "FreeRDP: second-host", focusHistoryID: 0 };
                     root.check(dock.apps.length === 1 && dock.apps[0].windows.length === 2, "Different RDP hosts must share one dock identity");
                     root.check(dock.apps[0].key === "windows-vm", "RDP must resolve the Windows launcher identity");
                     root.check(dock.apps[0].icon === dock.iconPath("windows-logo"), "RDP must use the launcher's Windows artwork");
                     root.check(dock.appKey("kitty", "terminal") === "kitty", "Unrelated window identities must remain unchanged");
                    // Games started outside Steam share class steam_app_0;
                    // their launching desktop entry identifies each one.
                    dock.launchedEntries = { "4242": "steam", "4343": "" };
                    dock.steamGames = { "777": { name: "Library game", icon: "" } };
                    first.lastIpcObject = { address: "0xfirst", initialClass: "steam_app_0", title: "Game", pid: 4242, focusHistoryID: 1 };
                    second.lastIpcObject = { address: "0xsecond", initialClass: "steam_app_0", title: "Other", pid: 4343, focusHistoryID: 0 };
                    root.check(dock.apps.length === 2, "Different launched games must not share the steam_app_0 tile");
                    const launched = dock.apps.find(app => app.key === "entry:steam");
                    root.check(launched && launched.entryId === "steam" && launched.name === DesktopEntries.byId("steam").name, "Launching desktop entry must name the game");
                    root.check(launched.icon === dock.iconPath(DesktopEntries.byId("steam").icon), "Launching desktop entry must supply artwork");
                    root.check(dock.apps.some(app => app.key === "steam_app_0" && app.name === "Steam Game"), "Unknown launches keep the Steam fallback");
                    second.lastIpcObject = { address: "0xsecond", initialClass: "steam_app_777", title: "Other", pid: 4343, focusHistoryID: 0 };
                    root.check(dock.apps.some(app => app.key === "steam_app_777" && app.name === "Library game"), "Steam library metadata must name games without launchers");
                    first.lastIpcObject = { address: "0xfirst", initialClass: "steam_app_2761858792", title: "Game", pid: 4242, focusHistoryID: 1 };
                    root.check(dock.apps.some(app => app.key === "steam_app_2761858792" && app.name === "Shortcut"), "Matching Steam launcher still takes precedence");
                    console.log("PASS: late metadata, squircle pixels, grouping, focus order, icon refresh, session ownership, close, Steam native/shortcut IDs, launcher artwork, desktop updates, fallback, launched entries, Steam library names");
                    Qt.quit();
                }
            } catch (error) {
                console.error("FAILED:", error.message);
                Qt.quit();
            }
        }
    }
    Timer {
        interval: 5000; running: true
        onTriggered: { console.error("FAILED: dock test timeout"); Qt.quit(); }
    }
}
