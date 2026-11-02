"""Device-local durable recovery records; no native database writes."""

import hashlib
import json
import os
from pathlib import Path

import checkpoint_store as store


class RecoveryError(ValueError):
    status = "failed"

    def __init__(self, reason, **details):
        super().__init__(reason)
        self.reason, self.details = reason, details

    def outcome(self):
        return {"status": self.status, "reason": self.reason, "details": self.details}


class RecoveryUnavailable(RecoveryError):
    status = "unavailable"


class RecoveryWaiting(RecoveryError):
    status = "waiting"


class RecoveryConflict(RecoveryError):
    status = "conflict"


def atomic_json(path, value):
    store.atomic(Path(path), store.canonical(value))


def read_intent(path):
    try:
        value = json.loads(Path(path).read_bytes())
        if not isinstance(value, dict):
            raise ValueError("Expected recovery object")
        return value
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as exc:
        raise RecoveryConflict("Corrupt recovery journal", path=str(path)) from exc


def clear_intent(path):
    path = Path(path)
    path.unlink(missing_ok=True)
    if path.parent.is_dir():
        store.fsync_dir(path.parent)


def begin_publication(path, base_revision, ledger, fingerprints):
    if read_intent(path) is not None:
        raise RecoveryConflict("Unreconciled publication intent", path=str(path))
    atomic_json(path, {"version": 1, "base_revision": base_revision,
                       "ledger": ledger, "fingerprints": fingerprints, "revision": None})


def finish_publication(path, revision):
    intent = read_intent(path)
    if intent is None:
        raise RecoveryConflict("Missing publication intent", path=str(path))
    intent["revision"] = revision
    atomic_json(path, intent)


def database_identity(database):
    database = Path(database).resolve()
    stat = database.stat()
    return hashlib.sha256(f"{database}:{stat.st_dev}:{stat.st_ino}".encode()).hexdigest()


def journal_root(database):
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return state / "context-chat/imports" / database_identity(database)


def pending_native_ids(database):
    result = set()
    if not Path(database).is_file():
        return result
    for path in journal_root(database).glob("*.json"):
        record = read_intent(path)
        if record and not record.get("complete"):
            result.update(record.get("ids", {}).values())
    return result


def preserved_families(database):
    """References for conflict/export UI; never delete or silently hide these copies."""
    result = []
    if not Path(database).is_file():
        return result
    for path in journal_root(database).glob("*.json"):
        record = read_intent(path)
        for family in record.get("preserved", []):
            result.append(dict(family, journal=str(path), content_hash=record["content_hash"]))
        if not record.get("complete"):
            result.append({"ids": record.get("ids", {}), "revision": record.get("revision"),
                           "reason": "interrupted import", "journal": str(path),
                           "content_hash": record.get("content_hash")})
    return result
