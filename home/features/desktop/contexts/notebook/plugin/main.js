const { Plugin, Notice, TFile } = require("obsidian");

const PHASES = ["Thoughts", "Todo", "In-Progress", "Done"];
const ALIASES = new Map([
    ["ideas", "Thoughts"], ["idea", "Thoughts"],
    ["outstanding questions", "Thoughts"], ["thoughts", "Thoughts"],
    ["todo", "Todo"], ["in-progress", "In-Progress"], ["done", "Done"],
]);

function phase(value) {
    if (value === undefined || value === null || value === "") return "Thoughts";
    return typeof value === "string" ? ALIASES.get(value.trim().toLowerCase()) || value : value;
}

function eligible(path, frontmatter = {}) {
    return path.endsWith(".md") && !path.split("/").some(part => part.startsWith("."))
        && !["Templates", "Attachments"].includes(path.split("/")[0])
        && frontmatter.kanban !== false;
}

function update(frontmatter, { now, created, isNew = false }) {
    const status = phase(frontmatter.status);
    if (!PHASES.includes(status)) throw new Error(`Unknown Kanban status: ${JSON.stringify(status)}`);
    if (frontmatter["kanban-history"] !== undefined && !Array.isArray(frontmatter["kanban-history"]))
        throw new Error("kanban-history must be a list");
    let changed = false;
    if (!frontmatter.created) {
        frontmatter.created = created;
        frontmatter["created-source"] = isNew ? "obsidian-create" : "filesystem-estimate";
        changed = true;
    }
    if (frontmatter.status !== status) {
        frontmatter.status = status;
        changed = true;
    }
    const history = frontmatter["kanban-history"] || [];
    if (!history.length || history[history.length - 1].status !== status) {
        history.push({ status, at: now, event: history.length || isNew ? "entered" : "observed" });
        frontmatter["kanban-history"] = history;
        changed = true;
    }
    return changed;
}

module.exports = class ContextNotebook extends Plugin {
    async onload() {
        this.pending = new Map();
        this.newFiles = new Set();
        this.ready = false;
        this.registerEvent(this.app.vault.on("create", file => {
            if (!this.ready || !(file instanceof TFile)) return;
            this.newFiles.add(file.path);
            this.schedule(file);
        }));
        this.registerEvent(this.app.metadataCache.on("changed", file => this.schedule(file)));
        this.registerEvent(this.app.vault.on("rename", file => this.schedule(file)));
        this.addCommand({ id: "open-board", name: "Open context Kanban", callback: () => this.openBoard() });
        this.app.workspace.onLayoutReady(async () => {
            this.ready = true;
            for (const file of this.app.vault.getMarkdownFiles()) this.schedule(file);
            await Promise.all(this.pending.values());
            await this.openBoard();
        });
    }

    schedule(file) {
        if (!this.ready || !(file instanceof TFile) || !eligible(file.path)) return;
        const key = file.path;
        const previous = this.pending.get(key) || Promise.resolve();
        const work = previous.then(() => this.record(file)).catch(error => {
            console.error("Context Notebook:", file.path, error);
            new Notice(`Cannot update Kanban metadata for ${file.basename}: ${error.message}`);
        });
        this.pending.set(key, work);
        work.finally(() => { if (this.pending.get(key) === work) this.pending.delete(key); });
    }

    async record(file) {
        const cache = this.app.metadataCache.getFileCache(file)?.frontmatter || {};
        if (!eligible(file.path, cache)) return;
        const facts = {
            now: new Date().toISOString(),
            created: new Date(file.stat.ctime).toISOString(),
            isNew: this.newFiles.has(file.path),
        };
        const probe = JSON.parse(JSON.stringify(cache));
        if (!update(probe, facts)) {
            this.newFiles.delete(file.path);
            return;
        }
        await this.app.fileManager.processFrontMatter(file, frontmatter => {
            if (eligible(file.path, frontmatter)) update(frontmatter, facts);
        });
        this.newFiles.delete(file.path);
    }

    async openBoard() {
        const file = this.app.vault.getAbstractFileByPath("Kanban.base");
        if (!(file instanceof TFile)) return;
        let board;
        this.app.workspace.iterateAllLeaves(leaf => {
            if (leaf.getViewState().state?.file === file.path) board = leaf;
        });
        if (board) await this.app.workspace.revealLeaf(board);
        else await this.app.workspace.getLeaf(false).openFile(file);
    }
};

module.exports.model = { PHASES, phase, eligible, update };
