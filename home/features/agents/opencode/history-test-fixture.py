"""Isolated metadata-only fixture for the real history CLI/UI adapter contract."""
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop/contexts"))
import context_chat_library as library
import contextctl as ctl
import checkpoint_store as store

if sys.argv[1] == "init":
    work = Path(os.environ["HOME"]) / "work"
    work.mkdir()
    owner = str(uuid.uuid4())
    metadata = Path(os.environ["CONTEXT_ROOT"]) / "History fixture/.context/context.json"
    ctl.atomic_json(metadata, {"version": 1, "id": owner, "name": "History fixture",
                               "working_directory": str(work), "repositories": []})
    (metadata.parent / "notes/.obsidian").mkdir(parents=True)
    context = ctl.find_context(owner)
    database = Path(os.environ["OPENCODE_DB"])
    marker = json.dumps({"desktop_context": {
        "id": context["id"], "chat": "ses_local", "session": "ses_local"}})
    if os.environ.get("OPENCODE_HISTORY_NATIVE"):
        fixture = work / "fixture.json"
        fixture.write_text(json.dumps({"info": {"id": "ses_local", "slug": "history-fixture", "projectID": "global",
            "directory": str(work), "title": "Local fixture", "version": "1.19.3",
            "time": {"created": 1, "updated": 1}}, "messages": []}))
        subprocess.run([os.environ["OPENCODE_HISTORY_NATIVE"], "import", str(fixture)], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with sqlite3.connect(database) as db:
            db.execute("UPDATE session SET metadata=? WHERE id='ses_local'", (marker,))
    else:
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE session (id TEXT, parent_id TEXT, directory TEXT, metadata TEXT, time_updated INTEGER, title TEXT)")
            db.execute("INSERT INTO session VALUES (?,NULL,?,?,?,?)", (
                "ses_local", str(work), marker, 1, "Local fixture"))
else:
    context = ctl.find_context(os.environ["CONTEXT_ID"])

archive = library.storage(context)
current = archive.load()
index = {"version": 1, "chats": {"ses_remote": {"fingerprint": "remote-revision", "deleted": False,
    "title": "Portable fixture" if sys.argv[1] == "init" else "Arrived update", "updated": 2, "source_device": "fixture-device"}}}
# Intentionally no transcript objects. Listing must still work and never import.
tree = store.Tree({"index.json": store.canonical(index)})
archive.publish(tree, {"context_id": context["id"], "device": "fixture-device", "warnings": []}, current)
print(json.dumps({"owner": context["id"]}))
