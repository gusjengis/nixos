"""Recovery fault injection against isolated native projection, never user data."""
import copy
from contextlib import closing, nullcontext
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import chat_portability as chat
import chat_recovery as recovery


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="recovery-", dir="/tmp/opencode")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.database = self.root / "native.db"
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TABLE session(id TEXT PRIMARY KEY)")
        self.native = {}
        self.imports = []
        self.crash = None
        self.bundle = self.root / "bundle"
        self.bundle.mkdir()
        files, sessions = {}, []
        for sid, parent in (("ses_parent", None), ("ses_child", "ses_parent")):
            info = {"id": sid, "directory": str(self.root), "metadata": {
                "desktop_context": {"id": "owner", "chat": "ses_parent", "session": sid}}}
            if parent:
                info["parentID"] = parent
            item = {"info": info, "messages": [{"info": {"id": "msg_" + sid}, "parts": []}]}
            raw = json.dumps(item).encode()
            name = sid + ".json"
            (self.bundle / name).write_bytes(raw)
            files[name] = {"sha256": hashlib.sha256(raw).hexdigest()}
            sessions.append({"id": sid, "file": name, "references": []})
        self.manifest = {"format": 1, "selection": {"session_id": "ses_parent"},
                         "root": str(self.root), "home": str(self.root),
                         "files": files, "sessions": sessions}
        (self.bundle / "manifest.json").write_text(json.dumps(self.manifest))
        self.enter = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root / "state")})
        self.enter.start()
        self.addCleanup(self.enter.stop)
        # Lock/process lifecycle is exercised by OC3; isolate recovery boundaries.
        worker = patch.dict("sys.modules", {"context_chat_worker": SimpleNamespace(
            scoped_lock=lambda *args, **kwargs: nullcontext())})
        worker.start()
        self.addCleanup(worker.stop)
        for name, value in (("_database", lambda cwd: sqlite3.connect(self.database)),
                            ("_export", lambda sid, cwd: copy.deepcopy(self.native[sid])),
                            ("_cli", self.cli)):
            mock = patch.object(chat, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    def cli(self, args, cwd):
        self.assertEqual(args[0], "import")
        item = json.loads(Path(args[1]).read_text())
        sid = item["info"]["id"]
        self.imports.append(sid)
        self.native[sid] = item
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("INSERT INTO session VALUES (?)", (sid,))
        if self.crash == "partial":
            self.native[sid]["messages"] = []
            raise SystemExit("native partial write")
        if self.crash == len(self.imports):
            raise SystemExit("crash after native commit")
        return ""

    def restore(self):
        return chat.restore(self.bundle, str(self.root))

    def test_crash_after_each_native_commit_resumes_without_duplicate_family(self):
        for boundary in (1, 2):
            with self.subTest(boundary=boundary):
                self.crash = boundary
                with self.assertRaises(SystemExit):
                    self.restore()
                pending = recovery.pending_native_ids(self.database)
                self.assertTrue(pending)
                self.crash = None
                selected = self.restore()
                self.assertIn(selected, self.native)
                self.assertEqual(len(self.imports), 2)
                self.assertEqual(self.restore(), selected)
                self.assertEqual(len(self.imports), 2)
                self.assertFalse(recovery.pending_native_ids(self.database))
            # Reset only this isolated fixture between boundaries.
            self.native.clear()
            self.imports.clear()
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute("DELETE FROM session")
            for path in recovery.journal_root(self.database).glob("*.json"):
                recovery.clear_intent(path)

    def test_partial_native_member_preserved_without_namespace_churn(self):
        self.crash = "partial"
        with self.assertRaises(SystemExit):
            self.restore()
        before = copy.deepcopy(self.native)
        self.crash = None
        for _ in range(3):
            with self.assertRaises(recovery.RecoveryConflict):
                self.restore()
        self.assertEqual(self.native, before)
        self.assertEqual(len(self.imports), 1)
        self.assertTrue(recovery.pending_native_ids(self.database))

    def test_verification_mismatch_never_reports_success(self):
        original = chat._export
        def broken(sid, cwd):
            item = original(sid, cwd)
            item["messages"] = []
            return item
        with patch.object(chat, "_export", broken):
            with self.assertRaises(recovery.RecoveryConflict):
                self.restore()
        self.assertTrue(recovery.pending_native_ids(self.database))

    def test_missing_corrupt_and_unavailable_are_distinct(self):
        artifact = self.bundle / "ses_child.json"
        raw = artifact.read_bytes()
        artifact.unlink()
        with self.assertRaises(recovery.RecoveryWaiting):
            self.restore()
        artifact.write_bytes(b"corrupt")
        with self.assertRaises(recovery.RecoveryConflict):
            self.restore()
        artifact.write_bytes(raw)
        with self.assertRaises(recovery.RecoveryUnavailable) as caught:
            chat.restore(self.bundle, str(self.root / "missing"))
        self.assertEqual(caught.exception.outcome()["status"], "unavailable")
        self.assertEqual(self.imports, [])
        self.restore()
        self.assertEqual(len(self.imports), 2)

    def test_completed_but_edited_copy_preserved_and_new_attempt_idempotent(self):
        old = self.restore()
        self.native[old]["info"]["title"] = "local edit"
        before = copy.deepcopy(self.native[old])
        new = self.restore()
        self.assertNotEqual(old, new)
        self.assertEqual(self.native[old], before)
        self.assertEqual(self.restore(), new)
        self.assertEqual(len(self.imports), 4)
        preserved = recovery.preserved_families(self.database)
        self.assertEqual(len(preserved), 1)
        self.assertIn(old, preserved[0]["ids"].values())

    def test_crash_at_every_journal_boundary_is_idempotent(self):
        original = recovery.atomic_json
        for boundary in range(1, 5):
            with self.subTest(boundary=boundary):
                count = 0
                def crash(path, value):
                    nonlocal count
                    original(path, value)
                    count += 1
                    if count == boundary:
                        raise SystemExit("journal boundary")
                with patch.object(recovery, "atomic_json", crash):
                    with self.assertRaises(SystemExit):
                        self.restore()
                selected = self.restore()
                self.assertEqual(self.restore(), selected)
                self.assertEqual(len(self.imports), 2)
            self.native.clear()
            self.imports.clear()
            with closing(sqlite3.connect(self.database)) as db, db:
                db.execute("DELETE FROM session")
            for path in recovery.journal_root(self.database).glob("*.json"):
                recovery.clear_intent(path)

    def test_failed_initial_journal_write_never_imports(self):
        with patch.object(recovery, "atomic_json", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.restore()
        self.assertEqual(self.imports, [])
        self.assertEqual(len(self.native), 0)

    def test_corrupt_journal_blocks_instead_of_resetting_identity(self):
        self.crash = 1
        with self.assertRaises(SystemExit):
            self.restore()
        path = next(recovery.journal_root(self.database).glob("*.json"))
        path.write_text("truncated")
        self.crash = None
        with self.assertRaises(recovery.RecoveryConflict):
            self.restore()
        self.assertEqual(len(self.imports), 1)

    def test_crash_after_complete_record_reuses_verified_family(self):
        original = recovery.atomic_json
        def crash(path, value):
            original(path, value)
            if value.get("complete"):
                raise SystemExit("after durable completion")
        with patch.object(recovery, "atomic_json", crash):
            with self.assertRaises(SystemExit):
                self.restore()
        self.restore()
        self.assertEqual(len(self.imports), 2)

    def test_journal_atomic_failure_and_database_incarnation(self):
        self.crash = 1
        with self.assertRaises(SystemExit):
            self.restore()
        old_root = recovery.journal_root(self.database)
        renamed = self.database.with_suffix(".old")
        self.database.rename(renamed)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("CREATE TABLE session(id TEXT PRIMARY KEY)")
        self.assertNotEqual(old_root, recovery.journal_root(self.database))
        self.assertFalse(recovery.pending_native_ids(self.database))

    def test_publication_intent_survives_until_ledger_acknowledgement(self):
        path = self.root / "publication.json"
        ledger = {"chats": {"ses_parent": {"local_id": "ses_local"}}}
        recovery.begin_publication(path, "base", ledger, {"ses_parent": "fingerprint"})
        self.assertEqual(recovery.read_intent(path)["ledger"], ledger)
        with self.assertRaises(recovery.RecoveryConflict):
            recovery.begin_publication(path, "base", {}, {})
        recovery.finish_publication(path, "published")
        self.assertEqual(recovery.read_intent(path)["revision"], "published")
        recovery.clear_intent(path)
        self.assertIsNone(recovery.read_intent(path))


if __name__ == "__main__":
    unittest.main()
