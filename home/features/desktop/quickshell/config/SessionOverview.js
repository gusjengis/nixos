.pragma library

function workspaceName(window) {
    return window.workspace ? (window.workspace.address || window.workspace.name || "") : "";
}

function rank(window) {
    return window.focusHistoryID >= 0 ? window.focusHistoryID : 100000;
}

// Ownership comes exclusively from the session registry, never a title/class
// heuristic. Global scratchpads therefore cannot leak into every session card.
function overview(session, windows, monitors) {
    const owned = Array.isArray(session.windows) ? session.windows : [];
    const members = windows.filter(window => window.mapped && owned.includes(window.address));
    const groups = [];
    function ensureGroup(name, monitorId) {
        let group = groups.find(candidate => candidate.name === name && candidate.monitorId === monitorId);
        if (!group) {
            const monitor = monitors.find(candidate => candidate.id === monitorId);
            const scale = monitor && monitor.scale > 0 ? monitor.scale : 1;
            let label = "Workspace";
            for (const output of Object.keys(session.workspaces || {})) {
                const slots = session.workspaces[output];
                const slot = Array.isArray(slots) ? slots.indexOf(name) : -1;
                if (slot >= 0)
                    label = "Workspace " + (slot + 1);
            }
            for (const role of Object.keys(session.specials || {})) {
                if (session.specials[role] === name)
                    label = role.charAt(0).toUpperCase() + role.slice(1);
            }
            group = {
                name: name, label: label, monitorId: monitorId,
                monitor: monitor ? monitor.name : "",
                x: monitor ? monitor.x : 0, y: monitor ? monitor.y : 0,
                width: monitor ? monitor.width / scale : 1920,
                height: monitor ? monitor.height / scale : 1080,
                windows: [], backgroundWindows: [], special: name.startsWith("special:"),
                current: false, rank: 100000
            };
            groups.push(group);
        }
        return group;
    }
    for (const window of members) {
        const group = ensureGroup(workspaceName(window), window.monitor);
        group.windows.push(window);
        group.rank = Math.min(group.rank, rank(window));
    }
    // Remembered view, not focus history, determines what a session looks like.
    // Materialize even empty numbered workspaces: hiding a scratchpad onto an
    // empty desktop must not keep showing its last-focused window.
    for (const monitor of monitors) {
        const names = (session.workspaces || {})[monitor.name];
        const slot = (session.slots || {})[monitor.name] || 1;
        const normalName = Array.isArray(names) ? names[slot - 1] : "";
        if (!normalName)
            continue;
        const normal = ensureGroup(normalName, monitor.id);
        const role = (session.visible_specials || {})[monitor.name];
        const specialName = (session.specials || {})[role];
        ensureGroup(specialName || normalName, monitor.id).current = true;
        for (const group of groups) {
            if (group.special && group.monitorId === monitor.id)
                group.backgroundWindows = normal.windows;
        }
    }
    groups.sort((a, b) => Number(b.current) - Number(a.current) || a.rank - b.rank || a.name.localeCompare(b.name));
    // Least recently focused windows first: the frontmost is painted last.
    for (const group of groups)
        group.windows.sort((a, b) => rank(b) - rank(a));
    return { groups: groups, windows: members.slice().sort((a, b) => rank(a) - rank(b)) };
}
