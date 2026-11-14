import QtQuick
import Quickshell
import Quickshell.Hyprland
import "menus"

// Dock adapter for the shared context menu. Items follow the macOS 27 Dock
// (MacOS Theme/29-dock-menu): the app's windows with a check on its main
// window, the app's own actions (desktop-entry actions here), Options ▸ Keep
// in Dock, then Quit.
// The Trash offers Open and Empty Trash. ContextMenus owns presentation.
Item {
    id: menu

    property var screen: null
    property var dockModel: null
    readonly property var node: ContextMenus.owner === menu ? ContextMenus.node : null
    readonly property bool open: node !== null
    property var heldItem: null
    onOpenChanged: if (!open) heldItem = null
    Component.onDestruction: close()

    function close() { ContextMenus.close(menu); }

    function present(item, entries, x, bottom, activate) {
        heldItem = item;
        ContextMenus.open({owner: menu, screen: screen, entries: entries,
            callout: {x: x, bottom: bottom}, activate: activate});
    }

    function row(text, action, extra) {
        return Object.assign({text: text, enabled: true, isSeparator: false, buttonType: QsMenuButtonType.None,
            checkState: Qt.Unchecked, icon: "", shortcut: "", hasChildren: false, action: action}, extra || {});
    }
    readonly property var separator: ({text: "", enabled: false, isSeparator: true, hasChildren: false})

    function sections(groups) {
        const entries = [];
        for (const group of groups.filter(group => group.length)) {
            if (entries.length) entries.push(separator);
            entries.push(...group);
        }
        return entries;
    }

    // The Dock keeps the first and last 30 characters of long window titles.
    function windowTitle(address) {
        const toplevel = Hyprland.toplevels.values.find(window => "0x" + window.address === address);
        const title = Array.from(toplevel && toplevel.title ? toplevel.title : "");
        return title.length > 61 ? title.slice(0, 30).join("") + "…" + title.slice(-30).join("") : title.join("");
    }

    // macOS 27: Finder has no Options. A running app offers Keep in Dock
    // (checked when pinned); a pinned app that is not running offers Remove
    // from Dock and Open.
    function options(app) {
        if (app.permanent || !dockModel || !dockModel.canPin(app)) return [];
        const child = app.running
            ? row("Keep in Dock", {pin: app, keep: !app.pinned}, {buttonType: QsMenuButtonType.CheckBox,
                checkState: app.pinned ? Qt.Checked : Qt.Unchecked})
            : row("Remove from Dock", {pin: app, keep: false});
        return [row("Options", null, {hasChildren: true, children: [child]})];
    }

    function appEntries(app) {
        const folders = dockModel && app.entryId === dockModel.finderId && dockModel.hasSeparateSessionFolder
            ? [row("Open Desktop Folder", {sessionFolder: true})] : [];
        if (!app.running)
            return sections([options(app), [row("Open", {launch: app})].concat(folders)]);
        const windows = app.windows.map((address, index) => row(windowTitle(address) || app.name, {window: address}, {
            buttonType: QsMenuButtonType.CheckBox, checkState: index === 0 ? Qt.Checked : Qt.Unchecked
        }));
        const entry = app.entryId ? DesktopEntries.byId(app.entryId) : null;
        const actions = entry ? entry.actions.map(action => row(action.name, {desktopAction: action})) : [];
        return sections([windows, folders.concat(actions), options(app), [row("Quit", {quit: app})]]);
    }

    function openApp(item, app, x, bottom) {
        present(item, appEntries(app), x, bottom, entry => {
            const action = entry.action;
            if (action.window) focusWindow(action.window);
            else if (action.pin) dockModel.setPinned(action.pin, action.keep);
            else if (action.launch) dockModel.launch(action.launch);
            else if (action.sessionFolder) dockModel.openFiles(true);
            else if (action.desktopAction) action.desktopAction.execute();
            else if (action.quit) quit(action.quit);
        });
    }

    function openTrash(item, full, x, bottom) {
        present(item, [row("Open", "open"), separator, row("Empty Trash", "empty", {enabled: full})], x, bottom, entry => {
            if (entry.action === "open")
                Quickshell.execDetached([Quickshell.env("HOME") + "/.nix-profile/bin/strata", "trash:///"]);
            else emptyTrash();
        });
    }

    function focusWindow(address) {
        Quickshell.execDetached(["hyprctl", "eval", "require('sessions').focus_window('address:" + address + "', { preserve_cursor = true })"]);
    }

    // macOS asks applications to quit; closing every window is the Wayland analogue.
    function quit(app) {
        const closes = app.windows.map(address => "hl.dispatch(hl.dsp.window.close({ window = 'address:" + address + "' }))");
        if (closes.length) Quickshell.execDetached(["hyprctl", "eval", closes.join("; ")]);
    }

    // The Dock confirms before permanently erasing the Trash.
    function emptyTrash() {
        Quickshell.execDetached(["sh", "-c",
            "[ \"$(hyprland-dialog --title 'Empty Trash' --apptitle 'Are you sure you want to permanently erase the items in the Trash?' "
            + "--text \"You can't undo this action.\" --buttons 'Cancel;Empty Trash')\" = 'Empty Trash' ] && gio trash --empty"]);
    }
}
