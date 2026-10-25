"""Context-owned notebook API for agents and desktop readers. No Obsidian required."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode

import contextctl as ctl
import notebook
import organization

START = "<!-- context-notebook:work-state -->"
END = "<!-- /context-notebook:work-state -->"
WORK = re.compile(re.escape(START) + r"\n## Work state\n\n(.*?)\n" + re.escape(END), re.DOTALL)


def revision(text):
    return hashlib.sha256(text.encode()).hexdigest()


def phase(value):
    status = value.get("status")
    status = "Thoughts" if status in (None, "") else notebook.ALIASES.get(str(status).strip().lower(), status)
    if status not in notebook.PHASES:
        raise ctl.ContextError(f"Unknown Kanban status: {status!r}")
    return status


def resolve(identifier):
    if not identifier:
        raise ctl.ContextError("No owning saved context; notebook integration is inactive")
    contexts = ctl.scan()
    context = next((item for item in contexts if item["id"] == identifier), None)
    if context is None:
        raise ctl.ContextError("Owning context is unavailable; no fallback to another notebook")
    node = next(item for item in organization.resolve(contexts) if item["id"] == identifier)
    return Vault(Path(context["path"]) / ".context/notes", identifier, node["breadcrumb"])


class Vault:
    def __init__(self, directory, identifier, label=""):
        self.directory = Path(directory)
        self.identifier = identifier
        self.label = label or identifier

    def path(self, name):
        relative = Path(name)
        if (relative.is_absolute() or ".." in relative.parts or relative.suffix != ".md"
                or not relative.parts or not notebook.eligible(relative, {})):
            raise ctl.ContextError("Use an ordinary vault-relative Markdown note path")
        path = ctl.contained(self.directory, self.directory / relative)
        if path.is_symlink():
            raise ctl.ContextError("Notebook API does not edit symlinked notes")
        return path

    def load(self, name):
        path = self.path(name)
        text = notebook.read(path)
        _, metadata, _ = notebook.fields(text)
        if not notebook.eligible(Path(name), metadata):
            raise ctl.ContextError("Note is excluded from Kanban")
        return path, text, metadata

    def card(self, name):
        _, text, metadata = self.load(name)
        match = WORK.search(text)
        return {"path": name, "title": Path(name).stem, "status": phase(metadata),
                "created": metadata.get("created"), "revision": revision(text),
                "work_state": match[1] if match else "", "content": text}

    def cards(self, query="", status=None):
        words = set(re.findall(r"[\w-]{3,}", query.casefold())) - {
            "the", "and", "this", "that", "with", "what", "have", "should", "let", "continue",
        }
        rows = []
        for path in self.directory.rglob("*.md"):
            name = path.relative_to(self.directory)
            if path.is_symlink() or not notebook.eligible(name, {}):
                continue
            _, metadata, _ = notebook.fields(notebook.read(path))
            if not notebook.eligible(name, metadata):
                continue
            card = self.card(name.as_posix())
            if status and card["status"] != status:
                continue
            title, body = card["title"].casefold(), card["content"].casefold()
            score = sum(5 * (word in title) + (word in body) for word in words)
            if words and not score:
                continue
            history = metadata.get("kanban-history") or []
            card["last_phase_at"] = notebook.json_default(history[-1].get("at", "")) if history else ""
            card["score"] = score
            rows.append(card)
        rows.sort(key=lambda row: (-row["score"], row["title"].casefold(), row["path"]))
        return rows

    def listing(self, request):
        rows = self.cards(request.get("query", ""), request.get("status"))
        offset = max(0, int(request.get("offset", 0)))
        result, used = [], 0
        for row in rows[offset:]:
            summary = {key: row[key] for key in ("path", "title", "status")}
            size = len(json.dumps(summary, ensure_ascii=False))
            if used + size > 6000:
                break
            result.append(summary)
            used += size
        return {"context_id": self.identifier, "total": len(rows), "notes": result,
                "next_offset": offset + len(result) if offset + len(result) < len(rows) else None}

    def brief(self, query=""):
        cards = self.cards()
        relevant = {card["path"]: card["score"] for card in self.cards(query)} if query else {}
        order = {"In-Progress": 0, "Todo": 1, "Thoughts": 2, "Done": 3}
        cards.sort(key=lambda row: (order[row["status"]], -relevant.get(row["path"], 0),
                                   row["title"].casefold()))
        # Use actual phase history, not mtime (metadata maintenance changes mtime).
        done = sorted((row for row in cards if row["status"] == "Done"),
                      key=lambda row: row["last_phase_at"], reverse=True)
        current = [row for row in cards if row["status"] in ("In-Progress", "Todo")]
        thoughts = [row for row in cards if row["status"] == "Thoughts"]
        cards = current + done[:3] + thoughts + done[3:]
        counts = {status: sum(row["status"] == status for row in cards) for status in notebook.PHASES}
        result = {"context_id": self.identifier, "context": self.label, "vault": str(self.directory),
                  "snapshot_at": notebook.timestamp(), "counts": counts, "notes": [], "omitted": 0}
        for row in cards:
            item = {key: row[key] for key in ("path", "title", "status")}
            if row["status"] != "Thoughts" and row["work_state"]:
                item["return_point"] = row["work_state"][:300]
            if len(json.dumps(result, ensure_ascii=False)) + len(json.dumps(item, ensure_ascii=False)) > 5000:
                break
            result["notes"].append(item)
        result["omitted"] = len(cards) - len(result["notes"])
        return result

    def info(self, _request):
        return {"context_id": self.identifier, "context": self.label, "vault": str(self.directory)}

    def open(self, request):
        """Open a card in its context's isolated Obsidian profile."""
        path, _, _ = self.load(request["path"])
        item = ctl.launch_context()
        if item is None or item["id"] != self.identifier or not item.get("runtime_id"):
            raise ctl.ContextError("Active context changed; select the card again")
        ctl.notes(item["runtime_id"])
        profile = ctl.state_root() / "obsidian" / self.identifier
        uri = "obsidian://open?" + urlencode({"path": str(path)})
        ctl.spawn(["obsidian", f"--user-data-dir={profile}",
                   f"--class=context-notes-{self.identifier}", uri])
        if (ctl.launch_context() or {}).get("id") == self.identifier:
            ctl.evaluate("require('sessions').show_special('notes')")
        return {"context_id": self.identifier, "path": request["path"]}

    def read(self, request):
        card = self.card(request["path"])
        start = max(0, int(request.get("offset", 0)))
        limit = min(8000, max(1, int(request.get("limit", 6000))))
        text = card["content"]
        card["content"] = text[start:start + limit]
        card["next_offset"] = start + limit if start + limit < len(text) else None
        return card

    @contextmanager
    def lock(self):
        directory = ctl.state_root() / "notebooks"
        directory.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256(self.identifier.encode()).hexdigest()
        with (directory / f"{key}.lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def publish(self, path, text, expected=None):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".contextctl-", delete=False) as stream:
                temporary = stream.name
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            if expected is None:
                # Atomic exclusive publication; an existing card is never replaced.
                os.link(temporary, path)
            else:
                if revision(notebook.read(path)) != expected:
                    raise ctl.ContextError("Note changed since read; reread and reconcile before updating")
                os.chmod(temporary, path.stat().st_mode & 0o777)
                os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def create(self, request):
        title = request["title"].strip()
        if not title or len(title.encode()) > 200 or re.search(r'[/\\:*?"<>|\x00-\x1f]', title) or title.startswith("."):
            raise ctl.ContextError("Use a concise, recognizable title without filename separators")
        name = title + ".md"
        path = self.path(name)
        status = phase({"status": request.get("status")})
        now = notebook.timestamp()
        metadata = {"status": status, "created": now, "created-source": "agent-create",
                    "kanban-history": [{"status": status, "at": now, "event": "entered"}]}
        body = request.get("body", "")
        if body.startswith("---"):
            raise ctl.ContextError("Supply note body, not frontmatter")
        text = notebook.edit_fields(body, metadata)
        with self.lock():
            self.publish(path, text)
        return self.read({"path": name})

    def update(self, request):
        with self.lock():
            path, text, metadata = self.load(request["path"])
            expected = request["revision"]
            if revision(text) != expected:
                raise ctl.ContextError("Note changed since read; reread and reconcile before updating")
            before, now = phase(metadata), notebook.timestamp()
            after = phase({"status": request.get("status", before)})
            changes = {}
            if not metadata.get("created"):
                changes.update(created=notebook.timestamp(path.stat().st_mtime))
                changes["created-source"] = "filesystem-mtime-estimate"
            history = metadata.get("kanban-history", [])
            if not isinstance(history, list) or any(not isinstance(event, dict) for event in history):
                raise ctl.ContextError("Invalid kanban-history; preserve it for review")
            history = list(history)
            if not history or history[-1].get("status") != before:
                history.append({"status": before, "at": now, "event": "observed"})
            if before != after:
                history.append({"status": after, "at": now, "event": "entered"})
            if metadata.get("status") != after:
                changes["status"] = after
            if metadata.get("kanban-history") != history:
                changes["kanban-history"] = history
            updated = notebook.edit_fields(text, changes) if changes else text
            if "work_state" in request:
                state = request["work_state"].strip()
                if len(state) > 2000 or START in state or END in state:
                    raise ctl.ContextError("Keep work state concise, without internal marker strings")
                if text.count(START) != text.count(END) or text.count(START) > 1:
                    raise ctl.ContextError("Ambiguous work-state section; preserve it for review")
                block = f"{START}\n## Work state\n\n{state}\n{END}" if state else ""
                if START in updated:
                    if not WORK.search(updated):
                        raise ctl.ContextError("Work-state section was edited; reconcile it before updating")
                    updated = WORK.sub(lambda _: block, updated)
                elif state:
                    updated += ("\n" if not updated.endswith("\n") else "") + "\n" + block + "\n"
            notebook.fields(updated)
            if updated != text:
                self.publish(path, updated, expected)
        return self.read({"path": request["path"]})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", default=os.environ.get("CONTEXT_ID"))
    parser.add_argument("command", choices=("info", "brief", "list", "search", "read", "open", "create", "update"))
    args = parser.parse_args(argv)
    try:
        request = json.loads(sys.stdin.read() or "{}")
        if not isinstance(request, dict):
            raise TypeError("Expected a JSON object on stdin")
        vault = resolve(args.context)
        command = "listing" if args.command in ("list", "search") else args.command
        result = vault.brief(request.get("query", "")) if command == "brief" else getattr(vault, command)(request)
        print(json.dumps(result, ensure_ascii=False, default=notebook.json_default))
        return 0
    except (ctl.ContextError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f"context-notes: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
