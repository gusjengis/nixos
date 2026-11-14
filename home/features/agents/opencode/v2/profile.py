#!/usr/bin/env python3
"""Prepare an isolated V2 profile and finish late V1 writes without overwrites."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()))
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def ticks(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
    except (OSError, IndexError):
        return None


def old_process(pid, started):
    path = Path(f"/proc/{pid}")
    try:
        return path.stat().st_uid == os.getuid() and ticks(pid) == started and "-opencode-1." in str((path / "exe").resolve())
    except OSError:
        return False


def roots(database):
    with closing(sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)) as db:
        return [row[0] for row in db.execute("SELECT id FROM session WHERE parent_id IS NULL")]


def pending_selections(spec):
    try:
        output = subprocess.check_output([spec.get("tmux", "tmux"), "list-panes", "-a", "-F", "#{@persistence-chat}"], text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return []
    result = {}
    source = Path(spec["legacy_database"]).resolve()
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as db:
        for line in output.splitlines():
            try:
                value = json.loads(line)
                if not value.get("session_id") or Path(value.get("database", "")).resolve() != source:
                    continue
                if not old_process(value["pid"], value["pid_start_ticks"]):
                    continue
                selected = value["session_id"]
                root = selected
                seen = set()
                while True:
                    if root in seen:
                        raise RuntimeError("Invalid legacy conversation ancestry")
                    seen.add(root)
                    row = db.execute("SELECT parent_id,metadata FROM session WHERE id=?", (root,)).fetchone()
                    if not row:
                        break
                    if not row[0]:
                        marker = (json.loads(row[1]) if row[1] else {}).get("desktop_context", {})
                        ids = [item[0] for item in db.execute("WITH RECURSIVE family(id) AS (SELECT id FROM session WHERE id=? UNION SELECT s.id FROM session s JOIN family f ON s.parent_id=f.id) SELECT id FROM family", (root,))]
                        ids = sorted(set(ids) | {spec.get("aliases", {}).get(identity, identity) for identity in ids})
                        result[(root, value["pid"])] = {"root": root, "selected": selected, "ids": ids, "owner": marker.get("id"),
                                        "chat": marker.get("chat", root), "pid": value["pid"], "started": value["pid_start_ticks"]}
                        break
                    root = row[0]
            except (ValueError, KeyError, TypeError):
                continue
    return list(result.values())


def services(spec):
    sys.path.insert(0, spec["contexts"])
    import context_chat_library as library
    import contextctl as ctl
    return library, ctl


def environment(spec):
    os.environ.update(spec.get("base_environment", {}))
    os.environ.update(spec["environment"])
    os.environ["OPENCODE_DB"] = spec["database"]
    os.environ["OPENCODE_CONTEXT_HELPER"] = "1"
    for name in ("CONTEXT_ID", "CONTEXT_DIRECTORY", "OPENCODE_CONTEXT_SCOPE_FILE", "OPENCODE_CONTEXT_STATE_FILE"):
        os.environ.pop(name, None)


def native(spec, arguments, timeout=180):
    completed = subprocess.run([spec["binary"], *arguments], text=True, capture_output=True, timeout=timeout)
    if completed.returncode:
        raise RuntimeError("Native V2 operation failed: " + completed.stderr[-2000:])
    return completed.stdout


def migrate_claude(spec):
    with closing(sqlite3.connect(Path(spec["database"]).as_uri() + "?mode=ro", uri=True)) as db:
        values = [json.loads(row[0]) for row in db.execute("SELECT value FROM credential WHERE integration_id='anthropic' ORDER BY active DESC,time_created DESC,id DESC")]
    if any(value.get("methodID") == "claude-code" for value in values):
        return
    current = values[0] if values else None
    value = current if current and current.get("type") == "oauth" else None
    metadata = {"opencode-claude-auth/claude-code-oauth": "v1"}
    config = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
    file = config / ".credentials.json"
    if file.is_file():
        disk = json.loads(file.read_text()).get("claudeAiOauth", {})
        if isinstance(disk.get("accessToken"), str) and isinstance(disk.get("refreshToken"), str) and type(disk.get("expiresAt")) in (int, float) and disk["expiresAt"] >= 0:
            value = {"access": disk["accessToken"], "refresh": disk["refreshToken"], "expires": int(disk["expiresAt"])}
            metadata.update(source="file", configDir=str(config))
    if not value:
        return
    credential = {"id": "cred_claude_code_migrated", "integrationID": "anthropic", "label": "Claude Code", "active": True,
                  "value": {"type": "oauth", "methodID": "claude-code", "access": value["access"],
                            "refresh": value["refresh"], "expires": value["expires"], "metadata": metadata}}
    with tempfile.TemporaryDirectory(prefix="auth-migration-", dir=Path(spec["database"]).parent) as temporary:
        file = Path(temporary) / "credential.json"
        atomic(file, [credential])
        native(spec, ["auth", "import", str(file), "--standalone"])
    if current is None or current.get("type") == "oauth":
        native(spec, ["api", "POST", "/api/credential/" + credential["id"] + "/activate", "--standalone"])


def legacy_openai(value):
    if not value or value.get("type") != "oauth" or value.get("methodID") != "chatgpt-browser":
        return None
    return {"type": "oauth", "access": value["access"], "refresh": value["refresh"], "expires": value["expires"],
            "accountId": (value.get("metadata") or {}).get("accountID")}


def sync_legacy_credentials(spec):
    source = Path(spec["legacy_database"]).parent / "auth.json"
    baseline = Path(spec["database"]).parent / "auth.json"
    if not source.is_file() or not baseline.is_file():
        return
    try:
        latest = json.loads(source.read_text()).get("openai")
        initial = json.loads(baseline.read_text()).get("openai")
    except json.JSONDecodeError:
        return
    keys = ("type", "access", "refresh", "expires", "accountId")
    latest = {key: latest.get(key) for key in keys} if latest else None
    initial = {key: initial.get(key) for key in keys} if initial else None
    if not latest or latest.get("type") != "oauth" or latest == initial:
        return
    if not isinstance(latest["access"], str) or not isinstance(latest["refresh"], str) or type(latest["expires"]) is not int or latest["expires"] < 0:
        return
    with closing(sqlite3.connect(Path(spec["database"]).as_uri() + "?mode=ro", uri=True)) as db:
        row = db.execute("SELECT id,value FROM credential WHERE integration_id='openai' ORDER BY active DESC,time_created DESC,id DESC LIMIT 1").fetchone()
    current = legacy_openai(json.loads(row[1])) if row else None
    if not current or current == latest:
        return
    same_account_newer = bool(current.get("accountId")) and current["accountId"] == latest.get("accountId") and latest["expires"] > current["expires"]
    if current != initial and not same_account_newer:
        return
    digest = hashlib.sha256(json.dumps(latest, sort_keys=True).encode()).hexdigest()[:24]
    identity = "cred_legacy_openai_" + digest
    metadata = {"accountID": latest["accountId"]} if latest.get("accountId") else {}
    value = {"type": "oauth", "methodID": "chatgpt-browser", "access": latest["access"], "refresh": latest["refresh"],
             "expires": latest["expires"], "metadata": metadata}
    entry = {"id": identity, "integrationID": "openai", "label": "OAuth (migrated)", "active": False, "value": value}
    with tempfile.TemporaryDirectory(prefix="auth-handoff-", dir=Path(spec["database"]).parent) as temporary:
        file = Path(temporary) / "credential.json"
        atomic(file, [entry])
        native(spec, ["auth", "import", str(file), "--standalone"])
    with closing(sqlite3.connect(Path(spec["database"]).as_uri() + "?mode=ro", uri=True)) as db:
        unchanged = db.execute("SELECT id,value FROM credential WHERE integration_id='openai' ORDER BY active DESC,time_created DESC,id DESC LIMIT 1").fetchone()
    if unchanged == row:
        native(spec, ["api", "POST", "/api/credential/" + identity + "/activate", "--standalone"])
        print("Updated the V2 OpenAI connection from the latest V1 credential without renewing it")


def seed_ledgers(spec, selected=None, only=None):
    library, ctl = services(spec)
    source, target = Path(spec["legacy_database"]), Path(spec["database"])
    original = library.native_rows(source)
    current = library.native_rows(target)
    chosen = selected or {}
    contexts = ctl.scan(check_working_directories=False)
    known = {context["id"] for context in contexts}
    owners = {row["owner"] for row in original.values()}
    processing = [*contexts, *({"id": owner, "upgrade_orphan": True} for owner in owners - known)]
    for context in processing:
        old_ledger = ctl.read_json(library.ledger_path(context, source), {"chats": {}})["chats"]
        try:
            index = {} if context.get("upgrade_orphan") else library.read_index(context)[0]["chats"]
        except (OSError, ValueError):
            index = {}
        families = {}
        for row in original.values():
            if row["owner"] == context["id"] and not row["parent"]:
                families.setdefault(row["chat"], []).append(row)
        ledger = {"chats": {}}
        for origin, candidates in families.items():
            if only is not None and (context["id"], origin) not in only:
                continue
            previous = old_ledger.get(origin)
            source_row = next((row for row in candidates if previous and row["id"] == previous["local_id"]), None)
            source_row = source_row or max(candidates, key=lambda row: (row["updated"], row["id"]))
            target_id = chosen.get(source_row["id"], source_row["id"])
            if target_id not in current:
                continue
            entry = index.get(origin)
            with library.use_database(source):
                old_fp = library.chats.fingerprint(source_row["id"], source_row["directory"])
            with library.use_database(target):
                new_fp = library.chats.fingerprint(target_id, current[target_id]["directory"])
            equivalent = (previous and old_fp == previous["native"]) or (entry and old_fp == entry["fingerprint"])
            base = entry["fingerprint"] if entry and old_fp == entry["fingerprint"] else previous.get("source") if previous else None
            if entry and not previous and not equivalent:
                base = "upgrade-unverified-source"
            record = {"local_id": target_id, "source": base, "native": new_fp if equivalent else "upgrade-local:" + old_fp}
            if previous and previous.get("deleted"):
                record["deleted"] = True
            ledger["chats"][origin] = record
        library.save_ledger(context, target, ledger, set(ledger["chats"]))
    library.publish_scopes(contexts, target)


def verify(database):
    with closing(sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("V2 database integrity check failed")
        missing = db.execute("SELECT count(*) FROM session s LEFT JOIN session_v2 v ON v.id=s.id WHERE v.id IS NULL OR coalesce(v.parent_id,'')!=coalesce(s.parent_id,'') OR coalesce(v.title,'')!=coalesce(s.title,'') OR coalesce(v.metadata,'{}')!=coalesce(s.metadata,'{}')").fetchone()[0]
        if missing:
            raise RuntimeError("V2 migration changed session identity, title, ancestry, or metadata")
        return db.execute("SELECT count(*) FROM session_v2").fetchone()[0]


def prepare(spec):
    marker = Path(spec["environment"]["OPENCODE_HANDOFF_FILE"])
    destination = Path(spec["database"])
    if marker.is_file():
        existing = json.loads(marker.read_text())
        if existing.get("database") != str(destination.resolve()) or not destination.is_file():
            raise RuntimeError("Existing profile handoff does not match the requested V2 database")
        existing.update(spec)
        pending = {(entry["root"], entry["pid"]): entry for entry in existing.get("pending", [])}
        pending.update({(entry["root"], entry["pid"]): entry for entry in pending_selections(existing)})
        existing["pending"] = list(pending.values())
        atomic(marker, existing)
        if not existing.get("ready"):
            environment(existing)
            native(existing, ["session", "migrate-v1", "--standalone"])
            verify(destination)
            migrate_claude(existing)
            seed_ledgers(existing)
            existing["ready"] = True
            atomic(marker, existing)
        environment(existing)
        sync_legacy_credentials(existing)
        print("V2 profile already prepared")
        return
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination.parent.chmod(0o700)
    receipt = destination.parent / "upgrade.json"
    if not destination.exists():
        source = Path(spec["legacy_database"]).resolve()
        if source.is_file():
            temporary = destination.with_suffix(".migration")
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as reader, closing(sqlite3.connect(temporary)) as writer:
                reader.backup(writer, pages=4096, sleep=.05)
            temporary.chmod(0o600)
            temporary.replace(destination)
        atomic(receipt, {"source": str(source), "created": time.time(), "phase": "copied"})
    elif not receipt.is_file():
        raise RuntimeError("An existing V2 database without a handoff receipt was retained unchanged")
    source_auth = Path(spec["legacy_database"]).parent / "auth.json"
    if source_auth.is_file() and not (destination.parent / "auth.json").exists():
        shutil.copy2(source_auth, destination.parent / "auth.json")
        (destination.parent / "auth.json").chmod(0o600)
    state = Path(spec["state"])
    state.mkdir(parents=True, exist_ok=True)
    for name in ("model.json", "session.json"):
        source = Path(spec["legacy_state"]) / name
        if source.is_file() and not (state / name).exists():
            shutil.copy2(source, state / name)
    pending = pending_selections(spec) if Path(spec["legacy_database"]).is_file() else []
    environment(spec)
    native(spec, ["session", "migrate-v1", "--standalone"])
    count = verify(destination) if Path(spec["legacy_database"]).is_file() else 0
    migrate_claude(spec)
    library, _ = services(spec)
    fingerprints = {}
    if Path(spec["legacy_database"]).is_file():
        with library.use_database(Path(spec["legacy_database"])):
            for root in roots(spec["legacy_database"]):
                fingerprints[root] = library.chats.fingerprint(root, str(Path.home()))
    record = {**spec, "database": str(destination.resolve()), "pending": pending, "aliases": {}, "prepared_sessions": count, "prepared_at": time.time(), "active": False, "ready": False}
    atomic(marker, record)
    atomic(receipt, {"phase": "prepared", "families": fingerprints, "sessions": count})
    if Path(spec["legacy_database"]).is_file():
        seed_ledgers(record)
    record["ready"] = True
    atomic(marker, record)
    print(f"Prepared V2 profile: {count} sessions; {len(pending)} active V1 family handoff(s)")


def completed_turn(database, selected):
    with closing(sqlite3.connect(Path(database).as_uri() + "?mode=ro", uri=True)) as db:
        user = db.execute("SELECT id FROM message WHERE session_id=? AND json_extract(data,'$.role')='user' ORDER BY time_created DESC,id DESC LIMIT 1", (selected,)).fetchone()
        assistant = db.execute("SELECT data FROM message WHERE session_id=? AND json_extract(data,'$.role')='assistant' AND coalesce(json_extract(data,'$.summary'),0)=0 ORDER BY time_created DESC,id DESC LIMIT 1", (selected,)).fetchone()
    if not user:
        return True
    if not assistant:
        return False
    value = json.loads(assistant[0])
    return value.get("parentID") == user[0] and value.get("time", {}).get("completed") is not None and (value.get("finish") == "stop" or bool(value.get("error")))


def activate(spec):
    marker = Path(spec["environment"]["OPENCODE_HANDOFF_FILE"])
    record = json.loads(marker.read_text())
    launcher = (Path.home() / ".nix-profile/bin/opencode").resolve()
    if "v2/launch.py" not in launcher.read_text():
        raise RuntimeError("V2 launcher has not been installed; original profile remains active")
    record.update(active=True, launcher=str(launcher))
    atomic(marker, record)
    print("V2 profile activated")


def finalize(spec):
    marker = Path(spec["environment"]["OPENCODE_HANDOFF_FILE"])
    record = json.loads(marker.read_text())
    if record.get("completed_at") and not record.get("pending"):
        print("Profile handoff already complete")
        return
    ready_since = {}
    while True:
        record = json.loads(marker.read_text())
        installed = str((Path.home() / ".nix-profile/bin/opencode").resolve())
        if not record.get("active") or record.get("launcher") != installed:
            time.sleep(.5)
            continue
        active = [entry for entry in record.get("pending", []) if old_process(entry["pid"], entry["started"])]
        if not active:
            break
        for entry in active:
            if completed_turn(record["legacy_database"], entry["selected"]):
                since = ready_since.setdefault(entry["pid"], time.monotonic())
                if time.monotonic() - since >= 10 and old_process(entry["pid"], entry["started"]):
                    os.kill(entry["pid"], signal.SIGTERM)
            else:
                ready_since.pop(entry["pid"], None)
        time.sleep(.5)
    environment(record)
    sync_legacy_credentials(record)
    library, ctl = services(record)
    source, target = Path(record["legacy_database"]), Path(record["database"])
    if not source.is_file():
        record.update(pending=[], completed_at=time.time())
        atomic(marker, record)
        return
    receipt = json.loads((target.parent / "upgrade.json").read_text())
    selected = {}
    touched = set()
    with library.use_database(source):
        for root in roots(source):
            fingerprint = library.chats.fingerprint(root, str(Path.home()))
            if fingerprint == receipt.get("families", {}).get(root) and root not in {entry["root"] for entry in record.get("pending", [])}:
                continue
            row = library.native_rows(source, session=root).get(root)
            if row:
                context = ctl.selected_context(row["owner"])
                if context:
                    library.sync_context(context, source, only_chat=row["chat"])
            with tempfile.TemporaryDirectory(prefix="opencode-v1-tail-", dir=target.parent) as temporary:
                bundle = Path(temporary) / "bundle"
                library.chats.capture({"session_id": root, "database": str(source)}, bundle, str(Path.home()))
                with library.use_database(target):
                    newest = library.chats.restore(bundle, str(Path.home()))
            selected[root] = newest
            if newest != root:
                with library.use_database(target), closing(library.chats._database(str(Path.home()))) as db:
                    retained = db.execute("SELECT 1 FROM session WHERE id=?", (root,)).fetchone()
                if retained:
                    native(record, ["api", "PATCH", "/api/session/" + root, "--data", '{"archived":true}', "--standalone"])
            suffix = newest[len(root):] if newest.startswith(root) else None
            if suffix is not None:
                with library.use_database(source):
                    members = library.chats._descendants(root, str(Path.home()))
                record["aliases"].update({identity: identity + suffix for identity in members})
            if row:
                touched.add((row["owner"], row["chat"]))
    if touched:
        seed_ledgers(record, selected, touched)
    latest = json.loads(marker.read_text())
    for key in ("active", "launcher", "environment", "binary", "legacy_binary"):
        if key in latest:
            record[key] = latest[key]
    record["aliases"] = {**latest.get("aliases", {}), **record["aliases"]}
    record["pending"] = []
    atomic(marker, record)
    if touched:
        seed_ledgers(record, selected, touched)
    record["completed_at"] = time.time()
    atomic(marker, record)
    print(f"V1 late-write handoff completed: {len(selected)} family/families; original database retained")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "activate", "finalize"])
    parser.add_argument("specification", type=Path)
    args = parser.parse_args()
    specification = json.loads(args.specification.read_text())
    if args.action == "prepare":
        prepare(specification)
    elif args.action == "activate":
        activate(specification)
    else:
        finalize(specification)


if __name__ == "__main__":
    main()
