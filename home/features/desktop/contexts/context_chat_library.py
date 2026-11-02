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
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing, contextmanager
from contextvars import ContextVar
from pathlib import Path

import chat_portability as chats
import checkpoint_store as store
import contextctl as ctl
import organization
import context_chat_state as chat_state
import context_chat_worker as worker
import chat_recovery as recovery


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


def visibility(contexts, only=None, resolve_roots=True):
    nodes = {node["id"]: node for node in organization.resolve(contexts)}
    targets = {}

    def target(item):
        if item["id"] not in targets:
            path = Path(item["working_directory_path"])
            targets[item["id"]] = path.resolve() if resolve_roots else path
        return targets[item["id"]]

    # Canonicalize only roots relevant to requested scopes, once per root.
    return {context["id"]: [item for item in contexts if item["id"] == context["id"] or
            (context["id"] in nodes[item["id"]]["ancestors"] and target(item) == target(context))]
            for context in contexts if only is None or context["id"] in only}


def visible_contexts(context, contexts, resolve_roots=True):
    return visibility(contexts, only={context["id"]}, resolve_roots=resolve_roots)[context["id"]]


def storage(context):
    directory = ctl.contained(Path(context["path"]), Path(context["path"]) / ".context/state/chats")
    return store.Store(directory, local_root() / "stores" / context["id"])


def native_rows(database, owner=None, chat=None, session=None):
    if not database.is_file():
        return {}
    with use_database(database), closing(chats._database(str(Path.home()))) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(session)")}
        if "metadata" not in columns:
            return {}
        condition, parameters = "", []
        if owner is not None:
            condition += " WHERE json_extract(metadata, '$.desktop_context.id')=?"
            parameters.append(owner)
        if chat is not None:
            condition += (" AND" if condition else " WHERE") + " json_extract(metadata, '$.desktop_context.chat')=?"
            parameters.append(chat)
        if session is not None:
            condition += (" AND" if condition else " WHERE") + " id=?"
            parameters.append(session)
        rows = db.execute("SELECT id, parent_id, directory, metadata, time_updated, title FROM session" + condition, parameters).fetchall()
    result = {}
    pending_ids = recovery.pending_native_ids(database)
    for sid, parent, directory, raw, updated, title in rows:
        if sid in pending_ids:
            continue
        metadata = json.loads(raw) if raw else {}
        marker = metadata.get("desktop_context", {})
        if marker:
            result[sid] = {"id": sid, "parent": parent, "directory": directory,
                           "owner": marker["id"], "chat": marker["chat"],
                           "member": marker["session"], "updated": updated, "title": title}
    return result


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"ses_[A-Za-z0-9_-]+", value):
        raise ValueError("Invalid portable conversation identity")
    return value


def ledger_path(context, database):
    return local_root() / "databases" / database_key(database) / (context["id"] + ".json")


def sync_context(context, database, hydrate=False, only_chat=None):
    """Stage one family at a time; serialize only durable publication/bookkeeping."""
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
    intent_path = ledger_file.with_suffix(".publication.json")
    intent = recovery.read_intent(intent_path)
    if intent and (only_chat is None or only_chat in intent["fingerprints"]):
        with worker.scoped_lock(context["id"]):
            intent = recovery.read_intent(intent_path)
            if intent is None:
                ledger = ctl.read_json(ledger_file, {"chats": {}})
            else:
                matches = all(index["chats"].get(origin) == entry for origin, entry in intent["fingerprints"].items())
                if matches:
                    save_ledger(context, database, intent["ledger"], intent["fingerprints"])
                    ledger = ctl.read_json(ledger_file, {"chats": {}})
                    recovery.clear_intent(intent_path)
                elif (current or {}).get("id") == intent["base_revision"]:
                    recovery.clear_intent(intent_path)
                else:
                    raise recovery.RecoveryConflict("Archive advanced across interrupted publication; histories retained")
    rows = native_rows(database, context["id"], only_chat)
    pending_ids = recovery.pending_native_ids(database)
    rows = {sid: row for sid, row in rows.items() if sid not in pending_ids}
    roots = {}
    for row in rows.values():
        if row["owner"] == context["id"] and not row["parent"]:
            roots.setdefault(safe_id(row["chat"]), []).append(row)
    if not roots and not current:
        return
    changed = False
    changed_origins = set()
    origins = {only_chat} if only_chat else set(index["chats"]) | set(roots)
    for origin in sorted(origins):
        safe_id(origin)
        entry = index["chats"].get(origin)
        record = ledger["chats"].get(origin)
        if record and record["local_id"] in pending_ids:
            continue
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
            changed_origins.add(origin)
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
                    rows = native_rows(database, context["id"], origin)
                    native = rows[sid]
                    fingerprint = chats.fingerprint(sid, native["directory"])
                    record = {"local_id": sid, "source": entry["fingerprint"], "native": fingerprint}
                    ledger["chats"][origin] = record
                    # Imports are durable individually. A later timeout must not
                    # discard progress and repeatedly restore earlier histories.
                    save_ledger(context, database, ledger, {origin})
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
            with closing(chats._database(native["directory"])) as db:
                summary = db.execute("SELECT title, time_updated FROM session WHERE id=?", (native["id"],)).fetchone()
            index["chats"][origin] = {"fingerprint": manifest["fingerprint"], "deleted": False,
                                      "title": summary[0], "updated": summary[1],
                                      "source_device": socket.gethostname()}
            ledger["chats"][origin] = {"local_id": native["id"], "source": manifest["fingerprint"], "native": manifest["fingerprint"]}
            changed = True
            changed_origins.add(origin)
    if changed:
        tree.path("index.json").write_bytes(store.canonical(index))
        with worker.scoped_lock(context["id"], priority="selected" if only_chat else "maintenance"):
            if (archive.load() or {}).get("id") != (current or {}).get("id"):
                raise recovery.RecoveryWaiting("Archive changed while staging selected publication; retry")
            fingerprints = {origin: index["chats"].get(origin) for origin in changed_origins}
            recovery.begin_publication(intent_path, (current or {}).get("id"), ledger, fingerprints)
            committed, _ = archive.publish(tree, {"context_id": context["id"], "device": socket.gethostname(),
                                                 "reason": "chat-library", "created_ns": time.time_ns(), "warnings": []}, current)
            recovery.finish_publication(intent_path, committed["id"])
            save_ledger(context, database, ledger, origins)
            recovery.clear_intent(intent_path)
        return
    save_ledger(context, database, ledger, origins)


def save_ledger(context, database, ledger, origins):
    with worker.scoped_lock(context["id"], database=database, kind="ledger"):
        path = ledger_path(context, database)
        latest = ctl.read_json(path, {"chats": {}})
        for origin in origins:
            if origin in ledger["chats"]:
                latest["chats"][origin] = ledger["chats"][origin]
        recovery.atomic_json(path, latest)


def scope_path(context, database):
    key = hashlib.sha256(str(database.resolve()).encode()).hexdigest()
    return local_root() / "scopes" / key / (context["id"] + ".json")


def publish_scopes(contexts, database, visibility_only=False, only=None, resolve_roots=True):
    views = visibility(contexts, only=only, resolve_roots=resolve_roots)
    relevant = {item["id"] for visible in views.values() for item in visible}
    rows = {}
    if database.is_file() and not visibility_only:
        for owner in relevant:
            rows.update(native_rows(database, owner))
    hidden = set()
    if database.is_file() and not visibility_only:
        for context in contexts:
            if context["id"] not in relevant:
                continue
            ledger = ctl.read_json(ledger_path(context, database), {"chats": {}})
            for row in rows.values():
                if row["owner"] != context["id"] or row["parent"]:
                    continue
                record = ledger["chats"].get(row["chat"])
                deleted = record and record.get("deleted", False)
                if deleted or (record and row["id"] != record["local_id"]):
                    hidden.add(row["id"])
    labels = {node["id"]: node["breadcrumb"] for node in organization.resolve(contexts)}
    for context in contexts:
        if only is not None and context["id"] not in only:
            continue
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
                publish_scopes(contexts, database, visibility_only=True, resolve_roots=False)
            return True
    return False


def sync_all(contexts=None, database=None, hydrate=False, only=None, errors=None, scope_only=None):
    contexts = contexts if contexts is not None else ctl.scan(check_working_directories=False)
    if scope_only is None and only is not None:
        # Update selected owners and ancestors that can display their histories.
        views = visibility(contexts, resolve_roots=False)
        scope_only = {owner for owner, visible in views.items() if any(item["id"] in only for item in visible)}
    databases = [Path(database).resolve()] if database else known_databases()
    for path in databases:
        if not path.is_file() and hydrate and any(
                (only is None or context["id"] in only) and (storage(context).directory / "current.json").is_file()
                for context in contexts):
            with use_database(path):
                chats._cli(["db", "SELECT 1"], str(Path.home()))
        if not path.is_file():
            publish_scopes(contexts, path, only=scope_only, resolve_roots=False)
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
                except (ValueError, KeyError, OSError, RuntimeError, TimeoutError, sqlite3.Error, subprocess.SubprocessError) as exc:
                    if errors is None:
                        raise
                    errors.append((context["id"], exc))
        publish_scopes(contexts, path, only=scope_only, resolve_roots=False)


def sync_dirty(contexts, errors=None, limit=8):
    """Bound maintenance by changed native owners/archive heads, not vault count."""
    errors = errors if errors is not None else []
    for database in known_databases():
        if not database.is_file():
            continue
        rows = native_rows(database)
        stamps_path = local_root() / "databases" / database_key(database) / "dirty.json"
        stamps = ctl.read_json(stamps_path, {})
        dirty = []
        for context in contexts:
            owned = sorted((row["id"], row["updated"], row["title"]) for row in rows.values() if row["owner"] == context["id"])
            head = chat_state.head_token(storage(context).directory / "current.json")
            token = hashlib.sha256(store.canonical([owned, head])).hexdigest()
            if stamps.get(context["id"]) != token:
                dirty.append((context, token))
        # Audit dependencies that can change without a native timestamp update.
        # Reconcile one owner per minute, rather than sweeping closed libraries.
        now = time.time()
        if contexts and now >= stamps.get("_reconcile_after", now + 60):
            audit = contexts[stamps.get("_audit_index", 0) % len(contexts)]
            if not any(context["id"] == audit["id"] for context, _ in dirty):
                dirty.append((audit, None))
            stamps["_audit_index"] = stamps.get("_audit_index", 0) + 1
            stamps["_reconcile_after"] = now + 60
        stamps.setdefault("_reconcile_after", now + 60)
        offset = stamps.get("_cursor", 0) % len(dirty) if dirty else 0
        batch = (dirty[offset:] + dirty[:offset])[:limit]
        stamps["_cursor"] = offset + len(batch)
        # Slow owner does not hold publication of independent owners behind it.
        with ThreadPoolExecutor(max_workers=4) as pool:
            jobs = {pool.submit(sync_context, context, database, hydrate=False): context for context, _ in batch}
            for job in as_completed(jobs):
                context = jobs[job]
                try:
                    job.result()
                    head = chat_state.head_token(storage(context).directory / "current.json")
                    owned = sorted((row["id"], row["updated"], row["title"]) for row in rows.values() if row["owner"] == context["id"])
                    stamps[context["id"]] = hashlib.sha256(store.canonical([owned, head])).hexdigest()
                except (ValueError, KeyError, OSError, RuntimeError, TimeoutError, sqlite3.Error, subprocess.SubprocessError) as exc:
                    errors.append((context["id"], exc))
        write_json(stamps_path, stamps)
        if dirty:
            only = {context["id"] for context, _ in batch}
            views = visibility(contexts, resolve_roots=False)
            affected = {owner for owner, visible in views.items() if any(item["id"] in only for item in visible)}
            publish_scopes(contexts, database, only=affected, resolve_roots=False)


def reference(selection, contexts=None):
    database = Path(selection.get("database") or database_path()).resolve()
    if not selection.get("session_id"):
        return None
    rows = native_rows(database, session=selection["session_id"])
    row = rows.get(selection["session_id"])
    if not row:
        return None
    context = (next((item for item in contexts if item["id"] == row["owner"]), None)
               if contexts is not None else ctl.selected_context(row["owner"]))
    if not context:
        raise ValueError("Chat owner context is unavailable; ownership was not reassigned")
    sync_context(context, database, only_chat=row["chat"])
    return {"owner": row["owner"], "chat": row["chat"], "member": row["member"]}


def restore_reference(reference, database=None):
    database = Path(database or database_path()).resolve()
    result = ensure_conversation(reference["owner"], reference["chat"], reference["member"], database=database)
    if not result.get("session_id"):
        raise ValueError("Selected conversation member is unavailable")
    return result["session_id"], result["directory"]


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


def prepare():
    """Compatibility discovery command. Never hydrate or gate foreground sends."""
    return list_summaries()


def selected_context(owner=None):
    """Metadata-only scope resolution; work roots are checked only for an import."""
    launching = os.environ.get("CONTEXT_ID") or owner
    context = ctl.selected_context(launching)
    if context is None:
        raise ValueError("Launching context is unavailable")
    # Self-owned checks/imports need no hierarchy discovery at all.
    if owner == launching:
        return context, [context]
    contexts = [context if item["id"] == launching else item for item in ctl.known_contexts()]
    if owner is not None:
        selected = ctl.selected_context(owner)
        if selected is None:
            raise ValueError("Conversation owner is unavailable")
        contexts = [selected if item["id"] == owner else item for item in contexts]
    visible = visible_contexts(context, contexts, resolve_roots=False)
    if owner is None:
        return context, visible
    selected = next((item for item in visible if item["id"] == owner), None)
    if selected is None:
        raise ValueError("Conversation owner is outside the visible context scope")
    return selected, visible


def state_file(context, database):
    viewer = {"id": os.environ.get("CONTEXT_ID", context["id"])}
    scope = os.environ.get("OPENCODE_CONTEXT_SCOPE_FILE") or str(scope_path(viewer, database))
    return chat_state.state_path(scope)


def read_index(context):
    archive = storage(context)
    head_path = archive.directory / "current.json"
    # Capture before load: a concurrent replacement cannot be labelled validated.
    observed = chat_state.head_token(head_path)
    cache_path = local_root() / "indexes" / (context["id"] + ".json")
    cached = ctl.read_json(cache_path, {})
    if (observed is not None and cached.get("observed_head") == observed
            and "index" in cached
            and not list(archive.directory.glob("current.sync-conflict*.json"))
            and not list((archive.directory / "conflicts").glob("*.json"))):
        return cached["index"], cached["current"], str(head_path), observed
    current = archive.load()
    if current and current.get("context_id") != context["id"]:
        raise ValueError("Portable chat library belongs to a different context")
    view = archive.view(current) if current else store.Tree().path()
    index = json.loads((view / "index.json").read_bytes()) if (view / "index.json").is_file() else {"version": 1, "chats": {}}
    if chat_state.head_token(head_path) != observed:
        raise ValueError("Portable index changed while reading; retry")
    if current:
        write_json(cache_path, {"observed_head": observed, "index": index,
                               "current": {key: current.get(key) for key in ("id", "device", "context_id")}})
    return index, current, str(head_path), observed


def observe_conversation(context, database, origin, entry, current, head_path, observed, rows):
    path = state_file(context, database)
    ledger_file = ledger_path(context, database) if database.is_file() else None
    record = None
    # Archive head becomes visible before the local ledger commit. The durable,
    # database-local publication intent proves this exact entry came from our
    # selected native family, even during that window. A hostname alone cannot.
    intent = recovery.read_intent(ledger_file.with_suffix(".publication.json")) if ledger_file else None
    # Read after the journal: if the writer has already removed its intent,
    # the committed ledger must be visible to this read.
    if ledger_file:
        record = ctl.read_json(ledger_file, {"chats": {}})["chats"].get(origin)
    if entry and intent and intent.get("fingerprints", {}).get(origin) == entry:
        staged = intent.get("ledger", {}).get("chats", {}).get(origin)
        if staged and staged.get("source") == entry.get("fingerprint"):
            record = staged
    if chat_state.head_token(head_path) != observed:
        raise recovery.RecoveryWaiting("Portable index changed during observation; retry")
    family = [row for row in rows.values() if row["owner"] == context["id"] and row["chat"] == origin]
    root = next((row for row in family if not row["parent"] and
                 (not record or row["id"] == record["local_id"])), None)
    selection = None
    if root:
        ids = {root["id"]}
        while True:
            descendants = ids | {row["id"] for row in family if row["parent"] in ids}
            if descendants == ids:
                break
            ids = descendants
        selection = {"selected_root": root["id"],
                  "members": {row["member"]: row["id"] for row in family if row["id"] in ids},
                  "base_revision": record.get("source") if record else None}
    chat_state.observe(path, context["id"], origin,
                       known_revision=entry.get("fingerprint") if entry else None,
                       observed_head=observed, head_path=head_path,
                       source_device=entry.get("source_device") if entry else None,
                       availability="local" if root else "portable_only", selection=selection)
    if entry and entry.get("deleted"):
        chat_state.publish(path, context["id"], origin, freshness="deleted")
    elif root and not entry:
        chat_state.publish(path, context["id"], origin, freshness="local_only")
    return chat_state.get(path, context["id"], origin)


def list_summaries():
    context, visible = selected_context()
    database = database_path()
    try:
        with worker.scoped_lock("database-registry", kind="registry", timeout=0.05):
            write_json(local_root() / "databases.json", sorted({str(path) for path in known_databases()} | {str(database)}))
    except worker.Busy:
        pass  # Registration is maintenance, never a summary/readiness gate.
    rows = native_rows(database)
    snapshot = chat_state.read(state_file(context, database))["conversations"]
    summaries = []
    errors = []
    for item in visible:
        problem = None
        try:
            index, current, head_path, observed = read_index(item)
        except (ValueError, KeyError, OSError) as exc:
            # One unavailable library must not remove another library's summaries.
            problem = str(exc)
            cached = ctl.read_json(local_root() / "indexes" / (item["id"] + ".json"), {})
            index, current, head_path, observed = cached.get("index", {"chats": {}}), None, None, None
            errors.append({"owner": item["id"], "error": problem})
        local = {row["chat"]: row for row in rows.values() if row["owner"] == item["id"] and not row["parent"]}
        known = {record["chat"] for record in snapshot.values() if record["owner"] == item["id"]}
        for origin in sorted(set(index["chats"]) | set(local) | known):
            entry = index["chats"].get(origin)
            row = local.get(origin)
            previous = snapshot.get(chat_state.key(item["id"], origin))
            unchanged = (previous and previous.get("observed_head") == observed
                         and previous.get("head_path") == head_path
                         and previous.get("known_revision") == (entry or {}).get("fingerprint")
                         and (not row or previous.get("selected_root") == row["id"]))
            state = (previous if unchanged or not head_path else
                     observe_conversation(item, database, origin, entry, current, head_path, observed, rows))
            if problem:
                fields = {"availability": "waiting_data", "operation": {"phase": "failed", "error": problem}}
                if "conflict" in problem.lower() or "divergent" in problem.lower():
                    fields["freshness"] = "conflict"
                state = chat_state.publish(state_file(context, database), item["id"], origin, **fields)
            summaries.append({"owner": item["id"], "chat": origin,
                              "title": (entry or {}).get("title") or (row or {}).get("title") or origin,
                              "updated": (entry or {}).get("updated", (row or {}).get("updated", 0)),
                              "deleted": bool((entry or {}).get("deleted")), "state": state})
    return {"version": 1, "conversations": summaries, "errors": errors}


def check_conversation(owner, chat, session=None, database=None):
    safe_id(chat)
    context, _ = selected_context(owner)
    database = Path(database or database_path()).resolve()
    try:
        index, current, head_path, observed = read_index(context)
    except (ValueError, KeyError, OSError) as exc:
        fields = {"availability": "waiting_data", "operation": {"phase": "failed", "error": str(exc)}}
        if "Divergent" in str(exc) or "conflict" in str(exc).lower():
            fields["freshness"] = "conflict"
        chat_state.publish(state_file(context, database), owner, chat, **fields)
        raise recovery.RecoveryWaiting(str(exc)) from exc
    rows = native_rows(database, owner, chat)
    state = observe_conversation(context, database, chat, index["chats"].get(chat), current, head_path, observed, rows)
    if session and session not in rows:
        raise ValueError("Selected native conversation does not belong to this family")
    return state


def _ensure_conversation(owner, chat, member=None, expected_revision=None, database=None):
    safe_id(chat)
    context, _ = selected_context(owner)
    database = Path(database or database_path()).resolve()
    state = check_conversation(owner, chat, database=database)
    if expected_revision is not None and state.get("known_revision") != expected_revision:
        raise ValueError("Selected portable revision changed; refresh selection")
    path = state_file(context, database)
    if state.get("freshness") in {"deleted", "conflict"}:
        raise ValueError("Conversation is deleted or has conflicting histories")
    # A current local copy needs no transcript fingerprint or publication.
    if (not state.get("selected_root") or state.get("availability") != "local"
            or state.get("freshness") not in {"current_as_known", "local_only"}):
        if not Path(context["working_directory_path"]).is_dir():
            chat_state.publish(path, owner, chat, availability="missing_workdir", operation={"phase": "failed"})
            raise ValueError("Conversation working directory is unavailable")
        context["working_directory_available"] = True
        context["cwd"] = context["working_directory_path"]
        chat_state.publish(path, owner, chat, operation={"phase": "waiting_lock"})
        try:
            started = chat_state.publish(path, owner, chat, operation={"phase": "importing"})
            if not database.is_file():
                with use_database(database):
                    chats._cli(["db", "SELECT 1"], str(Path.home()))
            sync_context(context, database, hydrate=True, only_chat=chat)
            viewer = os.environ.get("CONTEXT_ID", owner)
            publish_scopes(ctl.known_contexts(), database, only={viewer}, resolve_roots=False)
            index, current, head_path, observed = read_index(context)
            record = ctl.read_json(ledger_path(context, database), {"chats": {}})["chats"].get(chat)
            entry = index["chats"].get(chat)
            if not record or not entry or record["source"] != entry["fingerprint"]:
                raise ValueError("Selected portable revision changed during import; retry")
            if entry.get("deleted"):
                chat_state.publish(path, owner, chat, freshness="deleted", availability="portable_only")
                raise ValueError("Selected conversation was deleted")
            rows = native_rows(database, owner, chat)
            # Limit mappings to the verified native family, excluding superseded copies.
            with use_database(database):
                ids = set(chats._descendants(record["local_id"], context["cwd"]))
            family = {row["member"]: row["id"] for row in rows.values() if row["id"] in ids}
            chat_state.publish(path, owner, chat, expected_generation=started["generation"],
                               expected_revision=started.get("known_revision"), selected_root=record["local_id"], members=family,
                               known_revision=entry["fingerprint"], base_revision=record["source"],
                               freshness="current_as_known", availability="local", observed_head=observed,
                               head_path=head_path, source_device=entry.get("source_device"),
                               operation={"phase": "idle"})
        except (ValueError, KeyError, OSError, RuntimeError, TimeoutError, sqlite3.Error, subprocess.SubprocessError) as exc:
            if isinstance(exc, chat_state.StateChanged):
                raise  # A newer authoritative publisher owns the operation now.
            fields = {"operation": {"phase": "failed", "error": str(exc)}}
            if isinstance(exc, recovery.RecoveryWaiting):
                fields["availability"] = "waiting_data"
            elif "wait for sync" in str(exc):
                fields["availability"] = "waiting_data"
            elif isinstance(exc, recovery.RecoveryUnavailable):
                fields["availability"] = "unavailable"
            elif isinstance(exc, recovery.RecoveryConflict) or "divergent" in str(exc):
                fields["freshness"] = "conflict"
            chat_state.publish(path, owner, chat, **fields)
            raise
    state = chat_state.get(path, owner, chat)
    session = state.get("members", {}).get(member) if member else state.get("selected_root")
    if not session:
        raise ValueError("Selected conversation member is unavailable")
    row = native_rows(database, owner, chat).get(session)
    if not row:
        raise ValueError("Selected native conversation is unavailable")
    return {**state, "session_id": session, "directory": row["directory"]}


def ensure_conversation(owner, chat, member=None, expected_revision=None, database=None):
    """Single-flight selected family; no unrelated archive or global library gate."""
    context, _ = selected_context(owner)
    database = Path(database or database_path()).resolve()
    path = state_file(context, database)
    def existing():
        state = check_conversation(owner, chat, database=database)
        if expected_revision is not None and state.get("known_revision") != expected_revision:
            raise ValueError("Selected portable revision changed; refresh selection")
        if state.get("availability") != "local" or state.get("freshness") not in {"current_as_known", "local_only"}:
            return None
        sid = state.get("members", {}).get(member) if member else state.get("selected_root")
        row = native_rows(database, owner, chat).get(sid)
        if not row:
            return None
        state = chat_state.publish(path, owner, chat, operation={"phase": "idle"})
        return {**state, "session_id": sid, "directory": row["directory"]}
    def operation(phase):
        if phase == "waiting_lock":
            chat_state.publish(path, owner, chat, operation={"phase": phase})
    try:
        return worker.selected_work(owner, database, chat, expected_revision,
                                    lambda: _ensure_conversation(owner, chat, member, expected_revision, database),
                                    check=existing, on_state=operation)
    except (worker.Busy, worker.Cancelled) as exc:
        chat_state.publish(path, owner, chat, operation={"phase": "cancelled" if isinstance(exc, worker.Cancelled) else "waiting_lock", "error": str(exc)})
        raise


def launch(native, arguments):
    # Helper commands are not interactive launches. In particular the TUI's
    # database-path lookup must never hydrate history or recurse into startup.
    if os.environ.get("OPENCODE_CONTEXT_HELPER") or (arguments and arguments[0] in {
            "db", "import", "export", "--version", "-v", "--help", "-h", "auth", "models"}):
        os.execv(native, [native, *arguments])
    directory = os.environ.get("CONTEXT_DIRECTORY")
    if os.environ.get("TMUX") and os.environ.get("TMUX_PANE"):
        result = subprocess.run(["tmux", "-S", os.environ["TMUX"].rsplit(",", 2)[0], "show-environment",
                                 "-t", os.environ["TMUX_PANE"], "CONTEXT_DIRECTORY"],
                                text=True, capture_output=True, timeout=5, check=False)
        if result.returncode == 0:
            directory = result.stdout.removeprefix("CONTEXT_DIRECTORY=").rstrip("\n")
    context = ctl.read_context(directory) if directory else None
    if context:
        database = database_path()
        # Publish conservative local visibility immediately, retaining old-copy
        # exclusions. Canonical aliases and portable imports refresh after UI startup.
        contexts = [context if item["id"] == context["id"] else item for item in ctl.known_contexts()]
        publish_scopes(contexts, database, visibility_only=True, only={context["id"]}, resolve_roots=False)
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
    commands.add_parser("prepare")
    commands.add_parser("list")
    for name in ("check", "ensure"):
        command = commands.add_parser(name)
        command.add_argument("--owner", required=True)
        command.add_argument("--chat", required=True)
        if name == "check":
            command.add_argument("--session")
        else:
            command.add_argument("--member")
            command.add_argument("--expected-revision")
    commands.add_parser("unowned")
    args = parser.parse_args()
    if args.command == "launch":
        launch(args.native, args.arguments)
    elif args.command in {"prepare", "list"}:
        print(json.dumps(prepare()))
    elif args.command == "check":
        print(json.dumps(check_conversation(args.owner, args.chat, args.session)))
    elif args.command == "ensure":
        print(json.dumps(ensure_conversation(args.owner, args.chat, args.member, args.expected_revision)))
    elif args.command == "unowned":
        print(json.dumps(unowned(ctl.find_context(os.environ["CONTEXT_ID"]))))
    elif os.environ.get("CONTEXT_ID"):
        context, visible = selected_context()
        sync_all(visible, database_path(), hydrate=False, only={item["id"] for item in visible}, scope_only={context["id"]})
    else:
        sync_all(hydrate=False)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as exc:
        print(f"opencode context library: {exc}", file=sys.stderr)
        sys.exit(1)
