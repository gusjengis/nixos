.pragma library

// Shared by browse, search and move destinations. No compositor calls here.
function children(nodes, parent) {
    return nodes.filter(node => node.parent_id === parent).sort((a, b) =>
        a.label.localeCompare(b.label, undefined, { sensitivity: "base", numeric: true }));
}

function fuzzyScore(query, value) {
    query = query.toLowerCase();
    value = value.toLowerCase();
    let at = -1, score = 0, previous = -2;
    for (let i = 0; i < query.length; ++i) {
        at = value.indexOf(query[i], at + 1);
        if (at < 0) return -1;
        score += 4;
        if (at === previous + 1) score += 8;
        if (at === 0 || /[\s/_.-]/.test(value[at - 1])) score += 12;
        score -= Math.min(at - previous - 1, 12);
        previous = at;
    }
    if (value === query) score += 120;
    else if (value.startsWith(query)) score += 45;
    return score;
}

function search(nodes, query) {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return nodes.slice();
    return nodes.map(node => {
        let score = 0;
        for (const word of words) {
            const name = fuzzyScore(word, node.label);
            const path = fuzzyScore(word, node.breadcrumb);
            if (name < 0 && path < 0) return null;
            score += Math.max(name < 0 ? -Infinity : name + 35, path);
        }
        return { node: node, score: score };
    }).filter(Boolean).sort((a, b) => b.score - a.score || a.node.label.localeCompare(b.node.label)).map(result => result.node);
}

function destinations(nodes, ids, query) {
    return search(nodes.filter(node => !ids.includes(node.id)
        && !node.ancestors.some(id => ids.includes(id))), query);
}

function highlights(label, query) {
    const positions = [];
    for (const word of query.toLowerCase().trim().split(/\s+/)) {
        if (!word || fuzzyScore(word, label) < 0) continue;
        let at = -1;
        for (const character of word) {
            at = label.toLowerCase().indexOf(character, at + 1);
            positions.push(at);
        }
    }
    return Array.from(label).map((character, index) => {
        const safe = character.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        return positions.includes(index) ? "<b><font color='#9ac7ff'>" + safe + "</font></b>" : safe;
    }).join("");
}
