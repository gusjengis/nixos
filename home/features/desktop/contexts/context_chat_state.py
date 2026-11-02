"""Device-local conversation readiness. No transcript, network, or native CLI IO.

Writers serialize only the tiny local snapshot replacement. Readers never lock.
Archive revisions are equality tokens; generation is local, monotonic bookkeeping.
"""

import copy
import fcntl
import hashlib
import json
import os
import tempfile
from pathlib import Path


FRESHNESS = {"local_only", "current_as_known", "unknown", "outdated", "conflict", "deleted"}
AVAILABILITY = {"local", "portable_only", "waiting_data", "missing_workdir", "unavailable"}


class StateChanged(RuntimeError):
    """Conditional worker completion lost its revision/generation race."""


def state_path(scope_file=None):
    override = os.environ.get("OPENCODE_CONTEXT_STATE_FILE")
    if override:
        return Path(override)
    scope_file = scope_file or os.environ.get("OPENCODE_CONTEXT_SCOPE_FILE")
    if not scope_file:
        raise ValueError("No context scope/state path")
    return Path(str(scope_file) + ".state.json")


def key(owner, chat):
    if not isinstance(owner, str) or not owner or "/" in owner:
        raise ValueError("Invalid conversation owner")
    if not isinstance(chat, str) or not chat or "/" in chat:
        raise ValueError("Invalid conversation chat")
    return owner + "/" + chat


def read(path):
    try:
        value = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {"version": 1, "generation": 0, "conversations": {}}
    if (value.get("version") != 1 or type(value.get("generation")) is not int
            or value["generation"] < 0 or not isinstance(value.get("conversations"), dict)):
        raise ValueError("Invalid conversation state")
    for identity, record in value["conversations"].items():
        _validate(record)
        if identity != key(record["owner"], record["chat"]):
            raise ValueError("Conversation state identity mismatch")
    return value


def get(path, owner, chat):
    return read(path)["conversations"].get(key(owner, chat))


def head_token(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _validate(record):
    key(record.get("owner"), record.get("chat"))
    if record.get("freshness") not in FRESHNESS or record.get("availability") not in AVAILABILITY:
        raise ValueError("Invalid conversation readiness")
    if not isinstance(record.get("members"), dict) or not isinstance(record.get("operation"), dict):
        raise ValueError("Invalid conversation mapping/operation")
    if any(not isinstance(member, str) or not isinstance(native, str)
           for member, native in record["members"].items()):
        raise ValueError("Invalid native member mapping")


def _write(path, value):
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, sort_keys=True, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _merge(snapshot, owner, chat, expected_generation, expected_revision, fields):
    """Apply one update to an in-memory snapshot; returns (record, changed)."""
    identity = key(owner, chat)
    previous = snapshot["conversations"].get(identity)
    if expected_generation is not None and (previous or {}).get("generation", 0) != expected_generation:
        raise StateChanged(f"Conversation generation changed: {identity}")
    if expected_revision is not None and (previous or {}).get("known_revision") != expected_revision:
        raise StateChanged(f"Conversation revision changed: {identity}")
    record = copy.deepcopy(previous) if previous else {
        "owner": owner, "chat": chat, "known_revision": None, "base_revision": None,
        "selected_root": None, "members": {}, "freshness": "unknown",
        "availability": "unavailable", "source_device": None,
        "observed_head": None, "head_path": None, "operation": {"phase": "idle"},
    }
    record.update(fields)
    if record["owner"] != owner or record["chat"] != chat:
        raise ValueError("Conversation identity is immutable")
    _validate(record)
    if previous == record:
        return record, False
    snapshot["generation"] += 1
    record["generation"] = snapshot["generation"]
    snapshot["conversations"][identity] = record
    return record, True


def _transaction(path, apply):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with Path(str(path) + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        snapshot = read(path)
        before = snapshot["generation"]
        result = apply(snapshot)
        if snapshot["generation"] != before:
            _write(path, snapshot)
        return result


def publish(path, owner, chat, *, expected_generation=None, expected_revision=None, **fields):
    """Merge a record atomically. Optional CAS guards stale worker completion.

    expected_generation is the *record* generation (0 for absent record).
    expected_revision compares the currently known portable revision when supplied.
    """
    return _transaction(path, lambda snapshot: _merge(
        snapshot, owner, chat, expected_generation, expected_revision, fields)[0])


def publish_many(path, updates):
    """All-or-nothing batch: one lock, one read, at most one fsync'd replacement.

    updates: iterable of dicts with owner, chat, optional expected_generation /
    expected_revision, and record fields. Any CAS failure aborts the whole batch.
    Returns records in input order.
    """
    updates = [dict(update) for update in updates]

    def apply(snapshot):
        working = copy.deepcopy(snapshot)
        records = []
        for update in updates:
            owner, chat = update.pop("owner"), update.pop("chat")
            records.append(_merge(working, owner, chat, update.pop("expected_generation", None),
                                  update.pop("expected_revision", None), update)[0])
        snapshot.clear()
        snapshot.update(working)
        return records
    return _transaction(path, apply)


def _observation(previous, known_revision, observed_head, head_path, source_device, availability):
    previous = previous or {}
    freshness = previous.get("freshness", "unknown")
    if freshness not in {"conflict", "deleted"}:
        if previous.get("selected_root"):
            freshness = "current_as_known" if previous.get("base_revision") == known_revision else "outdated"
        else:
            freshness = "unknown"
    fields = dict(known_revision=known_revision, observed_head=observed_head,
                  head_path=str(head_path) if head_path is not None else None,
                  source_device=source_device, freshness=freshness)
    if availability is not None:
        fields["availability"] = availability
    return fields


def observe(path, owner, chat, *, known_revision, observed_head=None,
            head_path=None, source_device=None, availability=None, selection=None):
    """Apply a validated incoming index observation without selecting native data.

    Computed under the state lock, so concurrent writers cannot interleave.
    Optional selection supplies the verified local root/members/base atomically.
    Local conflict/deletion require explicit reconciliation; unrelated
    operation failures do not erase them.
    """
    def apply(snapshot):
        previous = dict(snapshot["conversations"].get(key(owner, chat)) or {})
        # Publish local selection/base and observed revision together. A reader
        # must never see a new base paired with an old known revision (or vice versa).
        selection_fields = dict(selection or {})
        if set(selection_fields) - {"selected_root", "members", "base_revision"}:
            raise ValueError("Invalid local selection fields")
        previous.update(selection_fields)
        fields = _observation(previous, known_revision, observed_head, head_path, source_device, availability)
        fields.update(selection_fields)
        return _merge(snapshot, owner, chat, None, None, fields)[0]
    return _transaction(path, apply)


def observe_many(path, observations):
    """Batch observe: dicts with owner, chat, known_revision and optional
    observed_head/head_path/source_device/availability. One lock and write."""
    observations = list(observations)

    def apply(snapshot):
        records = []
        for item in observations:
            previous = snapshot["conversations"].get(key(item["owner"], item["chat"]))
            fields = _observation(previous, item["known_revision"], item.get("observed_head"),
                                  item.get("head_path"), item.get("source_device"), item.get("availability"))
            records.append(_merge(snapshot, item["owner"], item["chat"], None, None, fields)[0])
        return records
    return _transaction(path, apply)
