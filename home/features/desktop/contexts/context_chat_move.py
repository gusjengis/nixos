"""Explicit, retryable conversation ownership transfer through native DB tooling."""

import json
import uuid
from pathlib import Path

import context_chat_library as library


def destinations(session=None):
    contexts = library.ctl.known_contexts()
    pending = {}
    if session:
        database = library.database_path()
        library.safe_id(session)
        with library.use_database(database):
            root = library.chats._family_root(session, str(Path.home()))
        pending = library.ctl.read_json(_journal(database, root), {})
    return [{"id": node["id"], "title": node["breadcrumb"], "directory": node["working_directory_path"],
             "retry": pending.get("target") == node["id"]}
            for node in library.organization.resolve(contexts) if not node["is_group"]]


def _literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def _journal(database, root):
    return library.local_root() / "transfers" / library.database_key(database) / (root + ".json")


def move(session, target):
    database = library.database_path()
    library.safe_id(session)
    with library.use_database(database):
        root = library.chats._family_root(session, str(Path.home()))
        with library.worker.scoped_lock("chat-transfer", database=database, conversation=root, kind="family", timeout=5):
            return _move(database, session, root, target)


def _move(database, session, root, target):
    destination = library.ctl.find_context(target)
    journal = _journal(database, root)
    intent = library.ctl.read_json(journal, {})
    if intent:
        if intent["target"] != target:
            raise ValueError("Finish the interrupted move to its original destination first")
        source, _ = library.selected_context(intent["source"])
    else:
        row = library.native_rows(database, session=session).get(session)
        if not row:
            raise ValueError("Only context-owned conversations can be moved")
        source, _ = library.selected_context(row["owner"])
        if source["id"] == target:
            raise ValueError("Conversation already belongs to that context")
        state = library.check_conversation(source["id"], row["chat"], session, database)
        if state.get("selected_root") != root or state.get("freshness") not in {"local_only", "current_as_known"}:
            raise ValueError("Open the latest conversation before moving it")
        ids = library.chats._descendants(root, row["directory"])
        family = library.native_rows(database, source["id"], row["chat"])
        if not set(ids) <= family.keys():
            raise ValueError("Conversation has inconsistent subagent ownership")
        # First preserve the source. No ownership changes if capture fails.
        library.sync_context(source, database, only_chat=row["chat"])
        intent = {"source": source["id"], "target": target, "old_chat": row["chat"],
                  "new_chat": "ses_" + uuid.uuid4().hex, "ids": ids}
        library.recovery.atomic_json(journal, intent)

    rows = library.native_rows(database)
    family = [rows.get(sid) for sid in intent["ids"]]
    original = all(row and row["owner"] == intent["source"] and row["chat"] == intent["old_chat"] for row in family)
    moved = all(row and row["owner"] == target and row["chat"] == intent["new_chat"] for row in family)
    if original:
        # One native statement moves the entire family atomically. Preserve IDs,
        # directory, messages, permissions and all unrelated metadata. A fresh
        # portable identity permits moving back into a previously tombstoned owner.
        ids = ",".join(_literal(sid) for sid in intent["ids"])
        query = ("UPDATE session SET metadata=json_set(metadata, '$.desktop_context.id', " + _literal(target)
                 + ", '$.desktop_context.chat', " + _literal(intent["new_chat"]) + "), time_updated=time_updated+1"
                 + " WHERE id IN (" + ids + ") AND json_extract(metadata, '$.desktop_context.id')=" + _literal(intent["source"])
                 + " AND json_extract(metadata, '$.desktop_context.chat')=" + _literal(intent["old_chat"])
                 + " AND (SELECT count(*) FROM session WHERE id IN (" + ids
                 + ") AND json_extract(metadata, '$.desktop_context.id')=" + _literal(intent["source"])
                 + " AND json_extract(metadata, '$.desktop_context.chat')=" + _literal(intent["old_chat"])
                 + ")=" + str(len(family)) + " RETURNING id")
        changed = json.loads(library.chats._cli(["db", query, "--format", "json"], source["cwd"]))
        if {row["id"] for row in changed} != set(intent["ids"]):
            raise ValueError("Conversation changed during transfer; retry the move")
    elif not moved:
        raise ValueError("Interrupted transfer has conflicting ownership; histories retained")

    # Journal survives failures here. Repeating Move finishes publication without
    # changing identity again. Normal maintenance can also publish the new owner.
    library.sync_context(destination, database, only_chat=intent["new_chat"])
    library.sync_context(source, database, only_chat=intent["old_chat"])
    contexts = library.ctl.known_contexts()
    library.publish_scopes(contexts, database)
    old = library.chat_state.get(library.state_file(source, database), source["id"], intent["old_chat"])
    if old:
        library.chat_state.publish(library.state_file(source, database), source["id"], intent["old_chat"], freshness="deleted")
    journal.unlink()
    return {"owner": target, "chat": intent["new_chat"], "session_id": session, "context": destination["name"]}
