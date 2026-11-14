// Resolve current catalog ancestry, never filesystem ancestry or copied pins.
function ancestry(nodes, path) {
    const chain = [];
    const seen = new Set();
    let node = nodes.find(node => node.path === path);
    while (node && !seen.has(node.id)) {
        seen.add(node.id);
        if (node.path) chain.unshift(node.path);
        node = nodes.find(parent => parent.id === node.parent_id);
    }
    if (path && !chain.includes(path)) chain.push(path);
    return chain;
}

function strings(value) {
    return Array.isArray(value) ? [...new Set(value.filter(id => typeof id === "string"))] : [];
}

function normalize(value, finderId) {
    return {
        version: 2,
        // Version 1 pins become explicit local additions, not a frozen snapshot.
        pinned: strings(value.pinned).filter(id => id !== finderId),
        removed: strings(value.removed).filter(id => id !== finderId),
        order: strings(value.order)
    };
}

function resolve(paths, states, finderId) {
    let pinned = [];
    let order = [];
    for (const path of paths) {
        const state = normalize(states[path] || {}, finderId);
        pinned = pinned.filter(id => !state.removed.includes(id));
        for (const id of state.pinned)
            if (!pinned.includes(id)) pinned.push(id);
        order = state.order.concat(order.filter(key => !state.order.includes(key)));
    }
    pinned.sort((a, b) => {
        const ai = order.indexOf("entry:" + a);
        const bi = order.indexOf("entry:" + b);
        return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi);
    });
    return { pinned: pinned, order: order };
}
