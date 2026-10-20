"""Native OpenCode snapshots. No direct database writes or credential copying.

capture(selection, destination, cwd) returns the manifest; restore(bundle, cwd)
returns the selected local session ID, or None for home. The coordinator must
read selection from the TUI socket synchronously and validate its PID/pane ancestry.
Missing artifacts are fatal; unsupported git snapshots remain explicit caveats.
"""

from __future__ import annotations

import base64
import copy
import fcntl
import hashlib
import json
import mimetypes
import os
import socket
import sqlite3
import struct
import subprocess
import tempfile
from contextlib import closing
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import unquote, urlsplit

_source_database = ContextVar("checkpoint_source_database", default=None)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _cli(args, cwd):
    result = subprocess.run(["opencode", *args], cwd=cwd, text=True,
                            capture_output=True, timeout=30, check=False,
                            env=dict(os.environ, OPENCODE_DB=_source_database.get()) if _source_database.get() else None)
    if result.returncode:
        raise RuntimeError(f"opencode {args[0]} failed: {result.stderr[-2000:]}")
    return result.stdout


def _export(sid, cwd):
    data = json.loads(_cli(["export", sid], cwd))
    if data["info"]["id"] != sid or not isinstance(data["messages"], list):
        raise ValueError("Native export identity mismatch")
    return data


def _database(cwd):
    # Avoid starting native CLI (and its logs/caches) for unchanged captures.
    default = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "opencode/opencode.db"
    override = _source_database.get() or os.environ.get("OPENCODE_DB")
    path = Path(override or default)
    if not override and not path.is_file():
        # Nonstandard/channel installs are discovered once on changed/first use.
        path = Path(_cli(["db", "path"], cwd).strip())
    path = path.resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    columns = {row[1] for row in db.execute("PRAGMA table_info(session)")}
    if not {"id", "parent_id", "directory"} <= columns:
        db.close()
        raise RuntimeError("Unsupported OpenCode session schema")
    return db


def _descendants(sid, cwd):
    with closing(_database(cwd)) as db:
        rows = db.execute("WITH RECURSIVE tree(id) AS (SELECT id FROM session WHERE id=? "
                          "UNION SELECT s.id FROM session s JOIN tree t ON s.parent_id=t.id) "
                          "SELECT id FROM tree", (sid,)).fetchall()
    return sorted(row[0] for row in rows)


def _family_root(sid, cwd):
    with closing(_database(cwd)) as db:
        seen = set()
        while sid not in seen:
            seen.add(sid)
            row = db.execute("SELECT parent_id FROM session WHERE id=?", (sid,)).fetchone()
            if row is None:
                raise ValueError("Selected chat ancestry missing")
            if not row[0]:
                return sid
            sid = row[0]
    raise ValueError("Cyclic chat ancestry")


def _walk(value, visit, trail=()):
    if isinstance(value, dict):
        return {key: _walk(item, visit, (*trail, key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_walk(item, visit, (*trail, index)) for index, item in enumerate(value)]
    return visit(value, trail)


def _write(path, value):
    path.write_text(_json(value) + "\n")


def read_selection(endpoint: Path, pane_pid: int, tmux_socket: str, pane_id: str) -> dict:
    """Read a live route and reject stale tmux options/PID reuse (Linux only).

    Coordinator gets pane_pid from tmux -S <exact socket> display-message,
    never from the stored option itself. No request/ack file is necessary.
    """
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(str(endpoint))
        _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise ValueError("Chat socket has wrong owner")
        raw = bytearray()
        while b"\n" not in raw:
            chunk = connection.recv(4096)
            if not chunk or len(raw) + len(chunk) > 65536:
                raise ValueError("Invalid chat socket reply")
            raw.extend(chunk)
        result = json.loads(raw.split(b"\n", 1)[0])
        peer_pid, _, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if (result["pid"] != peer_pid or result["pane_id"] != pane_id
            or result["tmux_socket"] != tmux_socket or result["pane_pid"] != pane_pid):
        raise ValueError("Chat socket does not belong to requested pane")

    def proc(pid):
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return int(fields[1]), fields[19]

    if (proc(peer_pid)[1] != result["pid_start_ticks"]
            or proc(pane_pid)[1] != result["pane_start_ticks"]):
        raise ValueError("Stale chat process metadata")
    ancestor = peer_pid
    seen = set()
    while ancestor != pane_pid:
        if ancestor <= 1 or ancestor in seen:
            raise ValueError("Chat process is not in requested pane")
        seen.add(ancestor)
        ancestor = proc(ancestor)[0]
    return result


def capture(selection: dict, destination: Path, cwd: str) -> dict:
    token = _source_database.set(selection.get("database"))
    try:
        return _capture(selection, destination, cwd)
    finally:
        _source_database.reset(token)


def _capture(selection, destination, cwd):
    # A coordinator RAM tree supports the same artifact API as Path.
    if not hasattr(destination, "tree"):
        destination = Path(destination)
    selection = {key: selection[key] for key in ("session_id", "directory", "parent_id", "context_root") if key in selection}
    sid = selection.get("session_id")
    fingerprint = None
    if sid:
        family = _family_root(sid, cwd)
        ids = _descendants(family, cwd)
        with closing(_database(cwd)) as db:
            db.execute("BEGIN")
            records = {}
            placeholders = ",".join("?" for _ in ids)
            for table, column in (("session", "id"), ("message", "session_id"), ("part", "session_id")):
                records[table] = db.execute(f'SELECT * FROM "{table}" WHERE {column} IN ({placeholders}) ORDER BY id', ids).fetchall()
            fingerprint = _hash(records)
    previous = destination / "manifest.json"
    if previous.is_file():
        old = json.loads(previous.read_text())
        if old.get("fingerprint") == fingerprint and old["selection"] == selection:
            unchanged = True
            for entry in old["sessions"]:
                for reference in entry["references"]:
                    if reference.get("inline"):
                        continue
                    info = old["files"][reference["path"]]
                    if hashlib.sha256(Path(reference["original"]).read_bytes()).hexdigest() != info["sha256"]:
                        unchanged = False
            if unchanged:
                return old
        if hasattr(destination, "tree"):
            prefix = str(destination) + "/" if str(destination) else ""
            for name in list(destination.tree.files):
                if name.startswith(prefix):
                    del destination.tree.files[name]
        else:
            raise ValueError("Chat destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Chat destination must be empty")
    manifest = {"format": 2, "selection": selection, "root": str(Path(selection.get("context_root", cwd)).resolve()),
                "home": str(Path.home()), "sessions": [], "files": {}, "unsupported": [], "fingerprint": fingerprint}
    if not sid:
        _write(destination / "manifest.json", manifest)
        return manifest
    family = _family_root(sid, cwd)
    ids = _descendants(family, cwd)
    if sid not in ids:
        raise ValueError("Selected session missing")
    exports = {item: _export(item, cwd) for item in ids}
    if exports[sid]["info"].get("parentID") not in (None, *ids):
        manifest["unsupported"].append({"reason": "Selected child has an external parent; restore detaches it",
                                        "parent_id": exports[sid]["info"]["parentID"]})
    # Native export is not transactional across sessions. Reject observed changes.
    if ids != _descendants(family, cwd) or any(_export(item, cwd) != exports[item] for item in ids):
        raise RuntimeError("Chat changed during checkpoint; retry capture")
    (destination / "blobs").mkdir()

    def write(relative, value):
        path = destination / relative if hasattr(destination, "tree") else _safe(destination, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write(path, value)
        manifest["files"][relative] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def artifact(path, association):
        source = Path(path)
        if not source.is_absolute():
            source = Path(cwd) / source
        # Explicitly exclude machine-local authentication, even if referenced.
        resolved = source.resolve()
        if resolved.name in {"auth.json", "credentials.json", ".env"} or ".ssh" in resolved.parts:
            raise ValueError(f"Credential reference cannot be bundled: {source}")
        content = source.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        relative = f"blobs/{digest}"
        (destination / relative).write_bytes(content)
        manifest["files"][relative] = {"sha256": digest, "size": len(content)}
        return {"path": relative, "original": str(source), "association": association}

    for item, data in exports.items():
        references = []

        def collect(value, trail, references=references, item=item):
            if not isinstance(value, str):
                return value
            key = trail[-1] if trail else None
            if value.startswith("data:") and key == "url":
                content = value.encode()
                digest = hashlib.sha256(content).hexdigest()
                relative = f"blobs/{digest}"
                (destination / relative).write_bytes(content)
                manifest["files"][relative] = {"sha256": digest, "size": len(content)}
                references.append({"path": relative, "original": "inline", "association": list(trail), "inline": True})
                return "checkpoint-inline:" + digest
            if value.startswith("file://"):
                url = urlsplit(value)
                if url.netloc not in ("", "localhost"):
                    raise ValueError("Non-local file URL")
                references.append(artifact(unquote(url.path), list(trail)))
            elif key == "outputPath" or (key == "path" and "source" in trail):
                references.append(artifact(value, list(trail)))
            elif key in ("snapshot", "hash") and value and (key == "snapshot" or "parts" in trail):
                manifest["unsupported"].append({"session_id": item, "reference": value,
                                                "reason": "Git snapshot objects not bundled"})
            return value

        data = _walk(data, collect)
        relative = f"{item}.json"
        messages = []
        for message in data["messages"]:
            mid = message["info"]["id"]
            parts = []
            for part in message["parts"]:
                name = f"messages/{mid}/{part['id']}.json"
                write(name, part)
                parts.append(name)
            name = f"messages/{mid}/info.json"
            write(name, message["info"])
            messages.append({"info": name, "parts": parts})
        write(relative, {"info": data["info"], "messages": messages})
        manifest["sessions"].append({"id": item, "file": relative, "references": references})
    manifest["unsupported"].append({"reason": "Unsubmitted drafts and in-flight operations are not recovered"})
    _write(destination / "manifest.json", manifest)
    return manifest


def _equivalent(data):
    data = copy.deepcopy(data)
    # Native import assigns project/path and may update this timestamp.
    data["info"].pop("projectID", None)
    data["info"].pop("path", None)
    data["info"].get("time", {}).pop("updated", None)
    return data


def _safe(bundle, relative):
    path = (bundle / relative).resolve()
    if not path.is_relative_to(bundle.resolve()):
        raise ValueError("Bundle path escapes root")
    return path


def restore(bundle: Path, cwd: str, context_root: str | None = None) -> str | None:
    bundle = Path(bundle)
    manifest = json.loads((bundle / "manifest.json").read_text())
    if manifest["format"] not in (1, 2):
        raise ValueError("Unsupported chat bundle")
    for relative, info in manifest["files"].items():
        if hashlib.sha256(_safe(bundle, relative).read_bytes()).hexdigest() != info["sha256"]:
            raise ValueError(f"Corrupt chat artifact: {relative}")
    selected = manifest["selection"].get("session_id")
    if not selected:
        return None
    root = Path(context_root or cwd).resolve()

    def relocate(value):
        if not isinstance(value, str) or not value.startswith("/"):
            return value
        for old, new in ((manifest["root"], root), (manifest["home"], Path.home())):
            try:
                return str(new / Path(value).relative_to(old))
            except ValueError:
                pass
        return value

    data = {}
    directories = {}
    for entry in manifest["sessions"]:
        item = json.loads(_safe(bundle, entry["file"]).read_text())
        if manifest["format"] == 2:
            item["messages"] = [{"info": json.loads(_safe(bundle, m["info"]).read_text()),
                                 "parts": [json.loads(_safe(bundle, p).read_text()) for p in m["parts"]]}
                                for m in item["messages"]]
        for reference in entry["references"]:
            target = item
            trail = reference["association"]
            for key in trail[:-1]:
                target = target[key]
            blob = _safe(bundle, reference["path"])
            original = target[trail[-1]]
            if reference.get("inline"):
                target[trail[-1]] = blob.read_text()
            elif isinstance(original, str) and original.startswith("file://"):
                mime = target.get("mime") if isinstance(target, dict) else None
                mime = mime or mimetypes.guess_type(reference["original"])[0] or "application/octet-stream"
                target[trail[-1]] = f"data:{mime};base64," + base64.b64encode(blob.read_bytes()).decode()
            else:
                # outputPath/source associations must remain usable after bundle moves.
                state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "context-chat/blobs"
                state.mkdir(parents=True, exist_ok=True, mode=0o700)
                local = state / manifest["files"][reference["path"]]["sha256"]
                if not local.exists():
                    local.write_bytes(blob.read_bytes())
                    local.chmod(0o600)
                elif hashlib.sha256(local.read_bytes()).hexdigest() != local.name:
                    raise ValueError("Corrupt machine-local chat blob")
                target[trail[-1]] = str(local)
        def paths(value, trail):
            # Relocate structured paths only; never rewrite prose/tool command strings.
            return relocate(value) if trail and trail[-1] in ("directory", "cwd", "root", "path", "outputPath") else value
        item = _walk(item, paths)
        directories[entry["id"]] = item["info"]["directory"]
        if not Path(directories[entry["id"]]).is_dir():
            raise ValueError(f"Missing session directory: {directories[entry['id']]}")
        data[entry["id"]] = item
    if selected not in data:
        raise ValueError("Selected session absent from bundle")

    # Serialize local restores, not native database transactions. No existing IDs
    # are ever imported, so native conflict behavior cannot overwrite local data.
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "context-chat"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "restore.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        with closing(_database(cwd)) as db:
            existing = {row[0] for row in db.execute("SELECT id FROM session")}
        exact = all(sid in existing and _equivalent(_export(sid, directories[sid])) == _equivalent(item)
                    for sid, item in data.items())
        if exact:
            return selected
        digest = _hash({sid: _equivalent(item) for sid, item in data.items()})
        mapping_file = state / f"{digest}.json"
        identifiers = set(data)
        def identify(value, trail):
            if trail and trail[-1] == "id" and isinstance(value, str) and value.startswith(("msg_", "prt_", "ses_")):
                identifiers.add(value)
            return value
        for item in data.values():
            _walk(item, identify)
        # Keep native ID ordering (parts are exported by ID, messages use ID as
        # a timestamp tie-breaker), including nested tool attachment IDs.
        for revision in range(1000):
            namespace = digest if revision == 0 else _hash([digest, revision])
            mapping = {old: old + "_" + namespace[:32] for old in identifiers}
            rewritten = {sid: _walk(item, lambda value, trail, mapping=mapping: mapping.get(value, value) if isinstance(value, str) else value)
                         for sid, item in data.items()}
            # A selected child whose parent was not captured must not link to
            # an unrelated local parent generation.
            for item in rewritten.values():
                if item["info"].get("parentID") and item["info"]["parentID"] not in mapping.values():
                    item["info"].pop("parentID")
            if all(mapping[sid] not in existing
                   or _equivalent(_export(mapping[sid], directories[sid])) == _equivalent(item)
                   for sid, item in rewritten.items()):
                break
        else:
            raise RuntimeError("Too many divergent local snapshot versions")
        _write(mapping_file, {"content_hash": digest, "ids": mapping, "complete": False})
        # Parents first. Abort cycles before any native writes.
        pending = dict(rewritten)
        ordered = []
        while pending:
            ready = [sid for sid, item in pending.items()
                     if item["info"].get("parentID") not in {v["info"]["id"] for v in pending.values()}]
            if not ready:
                raise ValueError("Cyclic session ancestry")
            for sid in ready:
                ordered.append((sid, pending.pop(sid)))
        for sid, item in ordered:
            target = mapping[sid]
            if target in existing:
                if _equivalent(_export(target, directories[sid])) != _equivalent(item):
                    raise RuntimeError("Snapshot ID exists with divergent or partial data; preserved untouched")
                continue
            with tempfile.TemporaryDirectory(prefix="context-chat-") as temp:
                native = Path(temp) / "native.json"
                _write(native, item)
                _cli(["import", str(native)], directories[sid])
            actual = _export(target, directories[sid])
            if _equivalent(actual) != _equivalent(item):
                raise RuntimeError("Native import lost or changed data; partial snapshot retained, restore failed")
        _write(mapping_file, {"content_hash": digest, "ids": mapping, "complete": True})
        return mapping[selected]
