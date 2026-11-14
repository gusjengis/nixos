import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import patch

definition = importlib.util.spec_from_file_location("upgrade_profile", Path(__file__).with_name("profile.py"))
profile = importlib.util.module_from_spec(definition)
definition.loader.exec_module(profile)


class HandoffTests(unittest.TestCase):
    def test_credential_handoff_preserves_newer_or_switched_v2_connections(self):
        initial = {"type": "oauth", "access": "initial", "refresh": "initial-refresh", "expires": 100, "accountId": "account"}
        latest = {**initial, "access": "latest", "refresh": "latest-refresh", "expires": 200}
        for current, incoming, expected, race in [
            (initial, latest, True, False),
            ({**initial, "access": "other-refresh", "expires": 150}, latest, True, False),
            ({**initial, "access": "newer", "expires": 300}, latest, False, False),
            ({**initial, "accountId": "another-account"}, latest, False, False),
            (latest, latest, False, False),
            (initial, initial, False, False),
            (initial, {**latest, "expires": -1}, False, False),
            (initial, latest, False, True),
        ]:
            with self.subTest(current=current, incoming=incoming, race=race), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                old, new = root / "old", root / "new"
                old.mkdir()
                new.mkdir()
                (old / "auth.json").write_text(json.dumps({"openai": incoming}))
                (new / "auth.json").write_text(json.dumps({"openai": initial}))
                database = new / "opencode.db"
                value = {"type": "oauth", "methodID": "chatgpt-browser", "access": current["access"],
                         "refresh": current["refresh"], "expires": current["expires"],
                         "metadata": {"accountID": current["accountId"]}}
                with closing(sqlite3.connect(database)) as db, db:
                    db.execute("CREATE TABLE credential(id TEXT,integration_id TEXT,active INTEGER,time_created INTEGER,value TEXT)")
                    db.execute("INSERT INTO credential VALUES('original','openai',1,1,?)", (json.dumps(value),))
                activated = []

                def native(spec, arguments):
                    if arguments[:2] == ["auth", "import"]:
                        entry, = json.loads(Path(arguments[2]).read_text())
                        self.assertFalse(entry["active"])
                        self.assertEqual(entry["value"]["refresh"], incoming["refresh"])
                        with closing(sqlite3.connect(database)) as db, db:
                            db.execute("INSERT INTO credential VALUES(?,'openai',0,2,?)", (entry["id"], json.dumps(entry["value"])))
                            if race:
                                db.execute("UPDATE credential SET value='{}' WHERE id='original'")
                    else:
                        self.assertEqual(arguments[:2], ["api", "POST"])
                        self.assertTrue(arguments[2].endswith("/activate"))
                        activated.append(arguments[2])
                    return ""

                spec = {"database": str(database), "legacy_database": str(old / "opencode.db")}
                with patch.object(profile, "native", side_effect=native):
                    profile.sync_legacy_credentials(spec)
                self.assertEqual(bool(activated), expected)

    def test_only_a_completed_response_to_the_latest_user_can_close_v1(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "source.db"
            with closing(sqlite3.connect(database)) as db, db:
                db.execute("CREATE TABLE message(id TEXT,session_id TEXT,time_created INTEGER,data TEXT)")
                db.execute("INSERT INTO message VALUES('user','session',1,?)", (json.dumps({"role": "user"}),))
                for finish, completed, parent, expected in [
                    ("tool-calls", 3, "user", False), ("stop", None, "user", False),
                    ("stop", 3, "previous", False), ("stop", 3, "user", True),
                ]:
                    db.execute("DELETE FROM message WHERE id='assistant'")
                    db.execute("INSERT INTO message VALUES('assistant','session',2,?)", (json.dumps({
                        "role": "assistant", "parentID": parent, "finish": finish,
                        "time": {"completed": completed},
                    }),))
                    db.commit()
                    self.assertEqual(profile.completed_turn(database, "session"), expected)
                db.execute("INSERT INTO message VALUES('new-user','session',4,?)", (json.dumps({"role": "user"}),))
                db.commit()
                self.assertFalse(profile.completed_turn(database, "session"))

    def test_process_identity_never_accepts_an_unrelated_process(self):
        self.assertFalse(profile.old_process(os.getpid(), profile.ticks(os.getpid())))
        self.assertFalse(profile.old_process(os.getpid(), "wrong-start-time"))

    def test_unknown_existing_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "v2/opencode.db"
            database.parent.mkdir()
            database.write_bytes(b"existing destination must survive")
            spec = {"database": str(database), "legacy_database": str(root / "old.db"),
                    "environment": {"OPENCODE_HANDOFF_FILE": str(root / "profile.json")}}
            with self.assertRaisesRegex(RuntimeError, "retained unchanged"):
                profile.prepare(spec)
            self.assertEqual(database.read_bytes(), b"existing destination must survive")


if __name__ == "__main__":
    unittest.main()
