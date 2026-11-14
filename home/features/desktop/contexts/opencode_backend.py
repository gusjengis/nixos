"""Read-only OpenCode storage adapters and lossless portable V2 envelopes.

V2 exports remain opaque native transcripts. Temporary SQLite views adapt only
the read/index/fingerprint contract shared by the portable-library helpers.
They never rewrite either version's persistent tables.
"""

import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3


class Connection(sqlite3.Connection):
    protocol = 1


def load_profile(env=None, home=None):
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    state = Path(env.get("XDG_STATE_HOME", home / ".local/state"))
    path = state / "desktop-contexts/opencode-profile.json"
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return {}
    if value.get("protocol") != 2 or not isinstance(value.get("database"), str):
        raise RuntimeError("Invalid OpenCode profile handoff record")
    return value


def profile(env=None, home=None):
    value = load_profile(env, home)
    if not value or not value.get("active", True):
        return {}
    home = Path.home() if home is None else Path(home)
    if value.get("launcher") and str((home / ".nix-profile/bin/opencode").resolve()) != value["launcher"]:
        return {}
    return value


def default_database(env=None, home=None):
    env = os.environ if env is None else env
    home = Path.home() if home is None else Path(home)
    if env.get("OPENCODE_DB"):
        return Path(env["OPENCODE_DB"])
    legacy = Path(env.get("XDG_DATA_HOME", home / ".local/share")) / "opencode/opencode.db"
    selected = profile(env, home)
    if not selected:
        return legacy
    scope = env.get("OPENCODE_CONTEXT_SCOPE_FILE")
    if scope:
        # Existing V1 processes retain their original scope. Never let a new
        # default redirect their maintenance into the V2 working database.
        digest = Path(scope).parent.name
        state = Path(env.get("XDG_STATE_HOME", home / ".local/state"))
        try:
            registered = json.loads((state / "desktop-contexts/chat-library/databases.json").read_text())
        except FileNotFoundError:
            registered = []
        candidates = [selected["database"], selected.get("legacy_database", str(legacy)), *registered]
        for candidate in candidates:
            if hashlib.sha256(str(candidate).encode()).hexdigest() == digest:
                return Path(candidate)
        raise RuntimeError("Conversation scope does not identify a registered OpenCode database")
    return Path(selected["database"])


def pending_handoffs(database):
    selected = load_profile()
    if selected.get("database") != str(Path(database).resolve()):
        return []
    return selected.get("pending", [])


def pending_ids(database):
    return {identity for record in pending_handoffs(database) for identity in record["ids"]}


def connect(database):
    path = Path(database).resolve(strict=True)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, factory=Connection)
    try:
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_v2'").fetchone():
            state = db.execute("SELECT value FROM kv WHERE key='migration.v1-v2'").fetchone()
            if state and json.loads(state[0]).get("phase") != "completed":
                raise RuntimeError("OpenCode V2 history migration is still running")
            # Fresh V2 databases have no legacy rows and need no migration key.
            if not state and db.execute("SELECT 1 FROM sqlite_master WHERE name='session'").fetchone():
                if db.execute("SELECT 1 FROM main.session LIMIT 1").fetchone():
                    raise RuntimeError("OpenCode V2 history migration is not complete")
            db.protocol = 2
            columns = [row[1] for row in db.execute("PRAGMA main.table_info(session_v2)")
                       if row[1] not in {"time_viewed", "time_suspended", "resume_attempts"}]
            selected = ",".join('"' + name.replace('"', '""') + '"' for name in columns)
            db.execute("CREATE TEMP VIEW session AS SELECT " + selected + " FROM main.session_v2")
            db.executescript("""
                CREATE TEMP VIEW message AS
                    SELECT id,session_id,time_created,time_updated,
                        json_set(data,'$.role',CASE type WHEN 'user' THEN 'user'
                            WHEN 'assistant' THEN 'assistant' ELSE 'system' END,
                            '$.__opencode_v2_type',type,'$.__opencode_v2_seq',seq) AS data
                    FROM main.session_message;
                CREATE TEMP VIEW part AS
                    SELECT 'prt_v2_' || message_id || '_' || printf('%08d',ordinal) AS id,
                        message_id,session_id,time_created,time_updated,
                        json_set(data,'$.type',type) AS data
                    FROM main.session_part;
            """)
        db.execute("PRAGMA query_only=ON")
        return db
    except BaseException:
        db.close()
        raise


def wrap(data):
    """Expose V2's opaque payload through the library's existing artifact layout."""
    if not isinstance(data.get("info", {}).get("location"), dict):
        return data
    native = copy.deepcopy(data)
    info = native["info"]
    info["directory"] = info["location"]["directory"]
    info["_opencode_protocol"] = 2
    return {
        "info": info,
        "messages": [{
            "info": {"id": message["id"], "role": message["type"] if message["type"] in ("user", "assistant") else "system",
                     "time": message["time"]},
            "parts": [{"id": "prt_v2_" + message["id"], "type": "opencode-v2", "native": message}],
        } for message in native["messages"]],
    }


def unwrap(data):
    """Validate and recover a native V2 transfer before handing it to its CLI."""
    if data.get("info", {}).get("_opencode_protocol") != 2:
        return data
    info = copy.deepcopy(data["info"])
    info.pop("_opencode_protocol")
    directory = info.pop("directory")
    if info.get("location", {}).get("directory") != directory:
        raise ValueError("V2 portable working-directory identity mismatch")
    messages = []
    for envelope in data["messages"]:
        if len(envelope["parts"]) != 1:
            raise ValueError("Invalid V2 portable message envelope")
        part = envelope["parts"][0]
        native = part.get("native")
        if part.get("type") != "opencode-v2" or not isinstance(native, dict):
            raise ValueError("Invalid V2 portable native message")
        if native.get("id") != envelope["info"]["id"] or part["id"] != "prt_v2_" + native["id"]:
            raise ValueError("V2 portable message identity mismatch")
        messages.append(copy.deepcopy(native))
    return {"info": info, "messages": messages}
