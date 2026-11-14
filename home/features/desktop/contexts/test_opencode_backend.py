import copy
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import opencode_backend as backend


class BackendTests(unittest.TestCase):
    def test_rollback_to_a_different_launcher_restores_the_legacy_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {"XDG_DATA_HOME": str(root / "data"), "XDG_STATE_HOME": str(root / "state")}
            new = root / "new-launcher"
            old = root / "old-launcher"
            new.touch()
            old.touch()
            link = root / ".nix-profile/bin/opencode"
            link.parent.mkdir(parents=True)
            link.symlink_to(new)
            marker = root / "state/desktop-contexts/opencode-profile.json"
            marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps({"protocol": 2, "database": str(root / "new.db"), "active": True, "launcher": str(new)}))
            self.assertEqual(backend.default_database(env, root), root / "new.db")
            link.unlink()
            link.symlink_to(old)
            self.assertEqual(backend.default_database(env, root), root / "data/opencode/opencode.db")
    def test_profile_default_switch_preserves_an_existing_v1_scope(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {"XDG_DATA_HOME": str(root / "data"), "XDG_STATE_HOME": str(root / "state")}
            legacy = root / "data/opencode/opencode.db"
            native = root / "data/opencode-v2/opencode.db"
            self.assertEqual(backend.default_database(env, root), legacy)
            marker = root / "state/desktop-contexts/opencode-profile.json"
            marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps({"protocol": 2, "database": str(native), "legacy_database": str(legacy)}))
            self.assertEqual(backend.default_database(env, root), native)
            scope = root / "scopes" / hashlib.sha256(str(legacy).encode()).hexdigest() / "owner.json"
            env["OPENCODE_CONTEXT_SCOPE_FILE"] = str(scope)
            self.assertEqual(backend.default_database(env, root), legacy)
            env["OPENCODE_DB"] = str(native)
            self.assertEqual(backend.default_database(env, root), native)

    def test_unknown_scope_does_not_redirect_into_a_new_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            env = {"XDG_STATE_HOME": str(root), "OPENCODE_CONTEXT_SCOPE_FILE": str(root / "unknown/owner.json")}
            marker = root / "desktop-contexts/opencode-profile.json"
            marker.parent.mkdir()
            marker.write_text(json.dumps({"protocol": 2, "database": str(root / "new.db"), "legacy_database": str(root / "old.db")}))
            with self.assertRaisesRegex(RuntimeError, "registered OpenCode database"):
                backend.default_database(env, root)

    def test_pending_handoffs_apply_only_to_the_new_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marker = root / "desktop-contexts/opencode-profile.json"
            marker.parent.mkdir()
            marker.write_text(json.dumps({"protocol": 2, "database": str(root / "new.db"), "pending": [{"ids": ["ses_pending"]}]}))
            with patch.dict("os.environ", {"XDG_STATE_HOME": str(root)}):
                self.assertEqual(backend.pending_ids(root / "new.db"), {"ses_pending"})
                self.assertEqual(backend.pending_ids(root / "old.db"), set())

    def fixture(self, version=2, migrated=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        database = Path(temporary.name) / "opencode.db"
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript("""
                CREATE TABLE session(id TEXT PRIMARY KEY,parent_id TEXT,directory TEXT,title TEXT,metadata TEXT,time_updated INTEGER);
                CREATE TABLE message(id TEXT,session_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);
                CREATE TABLE part(id TEXT,message_id TEXT,session_id TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);
                INSERT INTO session VALUES('ses_legacy',NULL,'/legacy','Old table','{}',1);
            """)
            if version == 2:
                db.executescript("""
                    CREATE TABLE kv(key TEXT,value TEXT);
                    CREATE TABLE session_v2(id TEXT PRIMARY KEY,parent_id TEXT,directory TEXT,title TEXT,metadata TEXT,time_updated INTEGER);
                    CREATE TABLE session_message(id TEXT,session_id TEXT,type TEXT,seq INTEGER,time_created INTEGER,time_updated INTEGER,data TEXT);
                    CREATE TABLE session_part(message_id TEXT,session_id TEXT,ordinal INTEGER,type TEXT,time_created INTEGER,time_updated INTEGER,data TEXT);
                    INSERT INTO session_v2 VALUES('ses_native',NULL,'/native','Native table','{"desktop_context":{"id":"owner"}}',2);
                    ALTER TABLE session_v2 ADD COLUMN time_viewed INTEGER;
                    INSERT INTO session_message VALUES('msg_native','ses_native','user',1,1,2,'{"text":"Request"}');
                    INSERT INTO session_part VALUES('msg_native','ses_native',0,'text',1,2,'{"text":"Response"}');
                """)
                db.execute("INSERT INTO kv VALUES('migration.v1-v2',?)", (json.dumps({"phase": "completed" if migrated else "sessions"}),))
        return database

    def test_legacy_reads_are_unchanged_and_read_only(self):
        database = self.fixture(version=1)
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        with closing(backend.connect(database)) as db:
            self.assertEqual(db.protocol, 1)
            self.assertEqual(db.execute("SELECT id FROM session").fetchall(), [("ses_legacy",)])
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM session")
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)

    def test_native_views_select_new_tables_without_modifying_legacy_or_native_data(self):
        database = self.fixture()
        before = hashlib.sha256(database.read_bytes()).hexdigest()
        with closing(backend.connect(database)) as db:
            self.assertEqual(db.protocol, 2)
            self.assertEqual(db.execute("SELECT id FROM session").fetchall(), [("ses_native",)])
            self.assertEqual(db.execute("SELECT id FROM main.session").fetchall(), [("ses_legacy",)])
            row = db.execute("SELECT data FROM message").fetchone()[0]
            self.assertEqual(json.loads(row)["role"], "user")
            self.assertEqual(json.loads(row)["__opencode_v2_type"], "user")
            self.assertEqual(db.execute("SELECT id FROM part").fetchone()[0], "prt_v2_msg_native_00000000")
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("DELETE FROM main.session_v2")
        self.assertEqual(hashlib.sha256(database.read_bytes()).hexdigest(), before)

    def test_partial_native_migration_never_exposes_a_partial_library(self):
        with self.assertRaisesRegex(RuntimeError, "migration is still running"):
            backend.connect(self.fixture(migrated=False))

    def test_local_viewed_state_does_not_change_portable_session_fingerprints(self):
        database = self.fixture()
        with closing(backend.connect(database)) as reader:
            before = reader.execute("SELECT * FROM session").fetchall()
            with closing(sqlite3.connect(database)) as writer, writer:
                writer.execute("UPDATE session_v2 SET time_viewed=100")
            self.assertEqual(reader.execute("SELECT * FROM session").fetchall(), before)

    def test_native_envelope_roundtrip_preserves_all_fields_and_embedded_files(self):
        native = {"info": {"id": "ses_native", "location": {"directory": "/project"},
                           "metadata": {"desktop_context": {"id": "owner"}}},
                  "messages": [{"id": "msg_native", "type": "user", "text": "Request", "time": {"created": 1},
                                "files": [{"data": "AQID", "mime": "image/png", "source": {"type": "inline"}}]}]}
        original = copy.deepcopy(native)
        wrapped = backend.wrap(native)
        self.assertEqual(wrapped["info"]["directory"], "/project")
        self.assertEqual(backend.unwrap(wrapped), native)
        self.assertEqual(native, original)
        wrapped["messages"][0]["parts"][0]["native"]["id"] = "msg_other"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            backend.unwrap(wrapped)

    def test_legacy_transfers_are_not_reinterpreted_as_native(self):
        legacy = {"info": {"id": "ses_old", "directory": "/project"}, "messages": []}
        self.assertIs(backend.wrap(legacy), legacy)
        self.assertIs(backend.unwrap(legacy), legacy)


if __name__ == "__main__":
    unittest.main()
