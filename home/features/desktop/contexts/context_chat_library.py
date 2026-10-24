"""Context-owned portable OpenCode libraries; native SQLite is a local working index."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing, contextmanager
from contextvars import ContextVar
from pathlib import Path

import chat_portability as chats
import checkpoint_store as store
import contextctl as ctl
import organization


_batch = ContextVar("chat_library_sync_batch", default=None)


@contextmanager
def sync_batch():
    """Reuse successful library syncs within one checkpoint, never across saves."""
    token = _batch.set(set())
    try:
        yield
    finally:
        _batch.reset(token)


def local_root():
    return ctl.state_root() / "chat-library"


def database_path():
    return Path(os.environ.get("OPENCODE_DB", str(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "opencode/opencode.db"))).resolve()


def database_key(database):
    stat = database.stat()
    # A replaced/reset database at the same path needs fresh hydration, not deletions.
    return hashlib.sha256(f"{database.resolve()}:{stat.st_dev}:{stat.st_ino}".encode()).hexdigest()


@contextmanager
def library_lock(blocking=True):
    local_root().mkdir(parents=True, exist_ok=True, mode=0o700)
    with (local_root() / "library.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


@contextmanager
def use_database(database):
    token = chats._source_database.set(str(database))
    try:
        yield
    finally:
        chats._source_database.reset(token)


def write_json(path, value):
    if not path.exists() or ctl.read_json(path) != value:
        ctl.atomic_json(path, value)


def visibility(contexts):
    nodes = {node["id"]: node for node in organization.resolve(contexts)}
    targets = {item["id"]: Path(item["working_directory_path"]).resolve() for item in contexts}
    return {context["id"]: [item for item in contexts if item["id"] == context["id"] or
            (context["id"] in nodes[item["id"]]["ancestors"] and targets[item["id"]] == targets[context["id"]])]
            for context in contexts}


def visible_contexts(context, contexts):
    return visibility(contexts)[context["id"]]


def storage(context):
    directory = ctl.contained(Path(context["path"]), Path(context["path"]) / ".context/state/chats")
    return store.Store(directory, local_root() / "stores" / context["id"])


def native_rows(database):
    if not database.is_file():
        return {}
    with use_database(database), closing(chats._database(str(Path.home()))) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(session)")}
        if "metadata" not in columns:
            return {}
        rows = db.execute("SELECT id, parent_id, directory, metadata, time_updated FROM session").fetchall()
    result = {}
    for sid, parent, directory, raw, updated in rows:
        metadata = json.loads(raw) if raw else {}
        marker = metadata.get("desktop_context", {})
        if marker:
            result[sid] = {"id": sid, "parent": parent, "directory": directory,
                           "owner": marker["id"], "chat": marker["chat"],
                           "member": marker["session"], "updated": updated}
    return result


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"ses_[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid portable conversation identity")
    return value


def ledger_path(context, database):
    return local_root() / "databases" / database_key(database) / (context["id"] + ".json")


def sync_context(context, database, hydrate=False):
    """Caller holds library_lock. Publish only proven local changes; never merge divergence."""
    archive = storage(context)
    current = archive.load()
    if current and current.get("context_id") != context["id"]:
        raise ValueError("Portable chat library belongs to a different context")
    # Keep untouched conversation bytes lazy. Reading the small index is enough
    # to decide which conversations need work; accessed objects and publication
    # still receive the store's full integrity/conflict checks.
    tree = archive.view(current).tree if current else store.Tree()
    index = json.loads(tree.read("index.json")) if "index.json" in tree.files else {"version": 1, "chats": {}}
    ledger_file = ledger_path(context, database)
    ledger = ctl.read_json(ledger_file, {"chats": {}})
    rows = native_rows(database)
    roots = {}
    for row in rows.values():
        if row["owner"] == context["id"] and not row["parent"]:
            roots.setdefault(safe_id(row["chat"]), []).append(row)
    if not roots and not current:
        return
    changed = False
    for origin in sorted(set(index["chats"]) | set(roots)):
        safe_id(origin)
        entry = index["chats"].get(origin)
        record = ledger["chats"].get(origin)
        candidates = roots.get(origin, [])
        native = next((row for row in candidates if record and row["id"] == record["local_id"]), None)
        if not record and candidates:
            native = max(candidates, key=lambda row: (row["updated"], row["id"]))
        if entry and entry.get("deleted"):
            if native:
                with use_database(database):
                    fingerprint = chats.fingerprint(native["id"], native["directory"])
                if not record or fingerprint != record["native"]:
                    raise ValueError(f"Chat {origin} has local edits concurrent with portable deletion; both retained")
            if record:
                record["deleted"] = True
            continue
        # A known conversation removed from the same native database is an explicit deletion.
        if record and not native and entry and entry["fingerprint"] == record["source"]:
            entry["deleted"] = True
            record["deleted"] = True
            changed = True
            continue
        with use_database(database):
            fingerprint = chats.fingerprint(native["id"], native["directory"]) if native else None
            incoming = entry and (not record or entry["fingerprint"] != record["source"])
            if incoming:
                if native and fingerprint == entry["fingerprint"]:
                    record = {"local_id": native["id"], "source": entry["fingerprint"], "native": fingerprint}
                    ledger["chats"][origin] = record
                    incoming = False
                elif record and fingerprint != record["native"]:
                    raise ValueError(f"Chat {origin} has divergent local and portable edits; both retained")
                elif not hydrate:
                    continue
                else:
                    if not context["working_directory_available"]:
                        continue
                    bundle = local_root() / "restore" / database_key(database) / context["id"] / origin
                    archive.materialize(archive.view(current) / ("conversations/" + origin), bundle)
                    sid = chats.restore(bundle, context["cwd"], context_root=context["path"],
                                        work_root=context["working_directory_path"])
                    rows = native_rows(database)
                    native = rows[sid]
                    fingerprint = chats.fingerprint(sid, native["directory"])
                    record = {"local_id": sid, "source": entry["fingerprint"], "native": fingerprint}
                    ledger["chats"][origin] = record
                    # Imports are durable individually. A later timeout must not
                    # discard progress and repeatedly restore earlier histories.
                    write_json(ledger_file, ledger)
                    # Hydrated bytes have new machine-local IDs/paths. Do not republish them until edited.
                    continue
            if not native or (record and fingerprint == record["native"]):
                continue
            destination = tree.path("conversations/" + origin)
            previous_manifest = json.loads((destination / "manifest.json").read_bytes()) if (destination / "manifest.json").is_file() else {}
            work_root = previous_manifest.get("work_root", context["working_directory_path"])
            if not Path(native["directory"]).resolve().is_relative_to(Path(work_root).resolve()):
                configured = Path(context["working_directory_path"]).resolve()
                work_root = str(configured) if Path(native["directory"]).resolve().is_relative_to(configured) else native["directory"]
            selection = {"session_id": native["id"], "directory": native["directory"],
                         "context_root": context["path"], "work_root": work_root}
            manifest = chats.capture(selection, destination, native["directory"])
            index["chats"][origin] = {"fingerprint": manifest["fingerprint"], "deleted": False}
            ledger["chats"][origin] = {"local_id": native["id"], "source": manifest["fingerprint"], "native": manifest["fingerprint"]}
            changed = True
    if changed:
        tree.path("index.json").write_bytes(store.canonical(index))
        archive.publish(tree, {"context_id": context["id"], "device": socket.gethostname(),
                               "reason": "chat-library", "created_ns": time.time_ns(), "warnings": []}, current)
    write_json(ledger_file, ledger)


def scope_path(context, database):
    key = hashlib.sha256(str(database.resolve()).encode()).hexdigest()
    return local_root() / "scopes" / key / (context["id"] + ".json")


def publish_scopes(contexts, database, visibility_only=False):
    rows = native_rows(database) if database.is_file() and not visibility_only else {}
    hidden = set()
    if database.is_file() and not visibility_only:
        for context in contexts:
            ledger = ctl.read_json(ledger_path(context, database), {"chats": {}})
            for row in rows.values():
                if row["owner"] != context["id"] or row["parent"]:
                    continue
                record = ledger["chats"].get(row["chat"])
                deleted = record and record.get("deleted", False)
                if deleted or (record and row["id"] != record["local_id"]):
                    hidden.add(row["id"])
    views = visibility(contexts)
    labels = {node["id"]: node["breadcrumb"] for node in organization.resolve(contexts)}
    for context in contexts:
        visible = views[context["id"]]
        previous = ctl.read_json(scope_path(context, database), {})
        write_json(scope_path(context, database), {"context_id": context["id"],
                   "ids": sorted(item["id"] for item in visible),
                   "hidden": previous.get("hidden", []) if visibility_only else sorted(hidden),
                   "labels": {item["id"]: labels[item["id"]] for item in visible}})


def known_databases():
    values = ctl.read_json(local_root() / "databases.json", [])
    return sorted({Path(value).resolve() for value in values} | {database_path()})


def refresh_scopes(contexts):
    # Directory/hierarchy updates need no SQLite writes or OpenCode restart.
    with library_lock(blocking=False) as acquired:
        if acquired:
            for database in known_databases():
                publish_scopes(contexts, database, visibility_only=True)


def sync_all(contexts=None, database=None, hydrate=False, only=None, errors=None):
    contexts = contexts if contexts is not None else ctl.scan()
    with library_lock():
        databases = [Path(database).resolve()] if database else known_databases()
        for path in databases:
            if not path.is_file() and hydrate and any(
                    (only is None or context["id"] in only) and (storage(context).directory / "current.json").is_file()
                    for context in contexts):
                with use_database(path):
                    # Let OpenCode initialize/migrate its own schema before importing portable history.
                    chats._cli(["db", "SELECT 1"], str(Path.home()))
            if not path.is_file():
                publish_scopes(contexts, path)
                continue
            for context in contexts:
                if only is None or context["id"] in only:
                    key = (str(path), context["id"], hydrate)
                    completed = _batch.get()
                    if completed is not None and key in completed:
                        continue
                    try:
                        sync_context(context, path, hydrate=hydrate)
                        if completed is not None:
                            completed.add(key)
                    except (ValueError, KeyError, OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
                        if errors is None:
                            raise
                        errors.append((context["id"], exc))
            publish_scopes(contexts, path)


def reference(selection, contexts=None):
    database = Path(selection.get("database") or database_path()).resolve()
    if not selection.get("session_id"):
        return None
    rows = native_rows(database)
    row = rows.get(selection["session_id"])
    if not row:
        return None
    context = next((item for item in (contexts if contexts is not None else ctl.scan()) if item["id"] == row["owner"]), None)
    if not context:
        raise ValueError("Chat owner context is unavailable; ownership was not reassigned")
    sync_all(contexts, database, only={context["id"]})
    return {"owner": row["owner"], "chat": row["chat"], "member": row["member"]}


def restore_reference(reference, database=None):
    database = Path(database or database_path()).resolve()
    contexts = ctl.scan()
    context = next((item for item in contexts if item["id"] == reference["owner"]), None)
    if not context:
        raise ValueError("Chat owner context is unavailable")
    sync_all(contexts, database, hydrate=True, only={context["id"]})
    record = ctl.read_json(ledger_path(context, database))["chats"][reference["chat"]]
    with use_database(database):
        ids = set(chats._descendants(record["local_id"], context["cwd"]))
    row = next((row for row in native_rows(database).values() if row["id"] in ids and row["member"] == reference["member"]), None)
    if row is None:
        raise ValueError("Selected conversation member is unavailable")
    return row["id"], row["directory"]


def unowned(context, database=None):
    database = Path(database or database_path())
    if not database.is_file():
        return []
    with use_database(database), closing(chats._database(context["cwd"])) as db:
        rows = db.execute("SELECT id, title, directory, metadata FROM session WHERE parent_id IS NULL ORDER BY time_updated DESC").fetchall()
    target = Path(context["working_directory_path"]).resolve()
    return [{"id": sid, "title": title, "directory": directory} for sid, title, directory, raw in rows
            if not (json.loads(raw) if raw else {}).get("desktop_context")
            and Path(directory).resolve().is_relative_to(target)]


def launch(native, arguments):
    if os.environ.get("OPENCODE_CONTEXT_HELPER"):
        os.execv(native, [native, *arguments])
    directory = os.environ.get("CONTEXT_DIRECTORY")
    if os.environ.get("TMUX") and os.environ.get("TMUX_PANE"):
        result = subprocess.run(["tmux", "-S", os.environ["TMUX"].rsplit(",", 2)[0], "show-environment",
                                 "-t", os.environ["TMUX_PANE"], "CONTEXT_DIRECTORY"],
                                text=True, capture_output=True, timeout=5, check=False)
        if result.returncode == 0:
            directory = result.stdout.removeprefix("CONTEXT_DIRECTORY=").rstrip("\n")
    contexts = ctl.scan()
    context = next((item for item in contexts if directory and Path(item["path"]).resolve() == Path(directory).resolve()), None)
    if context:
        database = database_path()
        with library_lock():
            write_json(local_root() / "databases.json", sorted({str(path) for path in known_databases()} | {str(database)}))
        visible = visible_contexts(context, contexts)
        sync_all(contexts, database, hydrate=True, only={item["id"] for item in visible})
        os.environ.update(CONTEXT_ID=context["id"], CONTEXT_DIRECTORY=context["path"],
                          OPENCODE_CONTEXT_SCOPE_FILE=str(scope_path(context, database)))
    else:
        os.environ.pop("CONTEXT_ID", None)
        os.environ.pop("OPENCODE_CONTEXT_SCOPE_FILE", None)
    os.execv(native, [native, *arguments])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("launch")
    command.add_argument("native")
    command.add_argument("arguments", nargs=argparse.REMAINDER)
    commands.add_parser("sync")
    commands.add_parser("unowned")
    args = parser.parse_args()
    if args.command == "launch":
        launch(args.native, args.arguments)
    elif args.command == "unowned":
        print(json.dumps(unowned(ctl.find_context(os.environ["CONTEXT_ID"]))))
    else:
        sync_all(hydrate=True)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"opencode context library: {exc}", file=sys.stderr)
        sys.exit(1)
