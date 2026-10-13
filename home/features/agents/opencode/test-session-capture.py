import argparse
import contextlib
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HERE = Path(__file__).parent
capture = load(HERE / "session-capture.py", "capture")
extract = load(HERE.parents[3] / "system/hosts/omega/note-extract.py", "extract")


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.data = self.root / "data"
        self.data.mkdir()
        self.config = self.root / "config.json"
        self.settings = {"databases": ["opencode.db", "opencode-stable.db"],
                         "repositories": [{"paths": ["/test/nixos"],
                                           "remote": "git@github.com:gusjengis/nixos.git",
                                           "name": "NixOS configuration"}]}
        self.config.write_text(json.dumps(self.settings))
        self.args = argparse.Namespace(vault=self.vault, data=self.data, config=self.config,
                                       state=self.root / "state", device="pc", session=[], dry_run=False)
        self.db = self.database("opencode.db")
        self.add_session(self.db)

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def database(self, name):
        db = sqlite3.connect(self.data / name)
        db.executescript("""
            CREATE TABLE project (id TEXT PRIMARY KEY, worktree TEXT, name TEXT);
            CREATE TABLE session (id TEXT, project_id TEXT, parent_id TEXT, directory TEXT,
                                  title TEXT, time_created INTEGER, time_updated INTEGER);
            CREATE TABLE message (id TEXT, session_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT);
            CREATE TABLE part (id TEXT, message_id TEXT, time_created INTEGER, time_updated INTEGER, data TEXT);
        """)
        db.execute("INSERT INTO project VALUES (?,?,?)", ("a" * 40, "/test/nixos", "nixos"))
        db.commit()
        return db

    def add_session(self, db, sid="ses_one", updated=2000, parent=None, text="Extraction works now."):
        db.execute("INSERT INTO session VALUES (?,?,?,?,?,?,?)",
                   (sid, "a" * 40, parent, "/test/nixos", "Note extraction", 1000, updated))
        mid = sid + "_msg"
        db.execute("INSERT INTO message VALUES (?,?,?,?,?)", (mid, sid, 1100, 1100, '{"role":"user"}'))
        db.execute("INSERT INTO part VALUES (?,?,?,?,?)",
                   (sid + "_text", mid, 1200, 1200, json.dumps({"type": "text", "text": text})))
        db.commit()

    def run_capture(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return capture.capture(self.args)

    def files(self):
        return list((self.vault / "Sessions/OpenCode/Transcripts").glob("*/*.md"))

    def test_roundtrip_and_idempotence(self):
        self.assertEqual(self.run_capture(), 0)
        path = self.files()[0]
        before = path.stat().st_mtime_ns
        meta, body = extract.split_note(path.read_text())
        self.assertEqual(meta["revision"], capture.digest(body))
        self.assertEqual(path.stem, meta["session-key"])
        self.assertEqual(meta["repository-remote"], "https://github.com/gusjengis/nixos")
        self.assertIn("    Extraction works now.", body)
        self.assertEqual(self.run_capture(), 0)
        self.assertEqual(before, path.stat().st_mtime_ns)

    def test_independent_device_session_identity(self):
        self.run_capture()
        first, _ = extract.split_note(self.files()[0].read_text())
        self.args.device = "mac"
        self.run_capture()
        copies = [extract.split_note(p.read_text())[0] for p in self.files()]
        self.assertEqual(len(copies), 2)
        self.assertTrue(all(m["session-key"] == first["session-key"] for m in copies))
        self.assertTrue(all(m["repository-id"] == first["repository-id"] for m in copies))

    def test_duplicate_database_uses_freshest_copy(self):
        second = self.database("opencode-stable.db")
        self.add_session(second, updated=3000, text="Latest evidence")
        second.close()
        self.run_capture()
        self.assertEqual(len(self.files()), 1)
        self.assertIn("Latest evidence", self.files()[0].read_text())
        self.db.execute("UPDATE session SET time_updated=1500")
        self.db.commit()
        self.run_capture()
        self.assertIn("Latest evidence", self.files()[0].read_text())

    def test_live_database_is_read_only(self):
        dump = list(self.db.iterdump())
        self.run_capture()
        self.assertEqual(dump, list(self.db.iterdump()))

    def test_part_edits_advance_transcript_timestamp(self):
        self.run_capture()
        self.db.execute("UPDATE part SET time_updated=5000,data=?",
                        (json.dumps({"type": "text", "text": "Updated evidence"}),))
        self.db.commit()
        self.run_capture()
        meta, body = extract.split_note(self.files()[0].read_text())
        self.assertEqual(meta["updated"], capture.timestamp(5000))
        self.assertIn("Updated evidence", body)

    def test_child_sessions_excluded(self):
        self.add_session(self.db, sid="ses_child", parent="ses_one")
        self.run_capture()
        self.assertEqual(len(self.files()), 1)

    def test_selection_and_dry_run(self):
        self.add_session(self.db, sid="ses_other")
        self.args.session = ["ses_one"]
        self.args.dry_run = True
        self.run_capture()
        self.assertEqual(self.files(), [])
        self.args.dry_run = False
        self.run_capture()
        self.assertEqual(len(self.files()), 1)

    def test_config_pilot_allowlist_and_cli_override(self):
        self.add_session(self.db, sid="ses_other")
        self.settings["include_sessions"] = ["ses_one"]
        self.config.write_text(json.dumps(self.settings))
        self.run_capture()
        self.assertEqual(len(self.files()), 1)
        self.args.session = ["ses_other"]
        self.run_capture()
        self.assertEqual(len(self.files()), 2)

    def test_bad_session_does_not_block_healthy_session(self):
        self.add_session(self.db, sid="ses_bad", updated=4000)
        self.db.execute("UPDATE part SET data='not json' WHERE id='ses_bad_text'")
        self.db.commit()
        self.assertEqual(self.run_capture(), 1)
        self.assertEqual(len(self.files()), 1)

    def test_corrupt_export_does_not_block_other_sessions(self):
        self.run_capture()
        self.files()[0].write_text("damaged export")
        self.add_session(self.db, sid="ses_other", updated=4000)
        self.assertEqual(self.run_capture(), 1)
        self.assertEqual(len(self.files()), 2)

    def test_omit_internal_and_sensitive_parts(self):
        parts = [
            {"type": "reasoning", "text": "PRIVATE REASONING"},
            {"type": "file", "url": "data:SECRET ATTACHMENT"},
            {"type": "text", "synthetic": True, "text": "SYNTHETIC FILE SECRET"},
            {"type": "tool", "tool": "read", "state": {"status": "completed",
             "input": {"filePath": "/home/user/.config/secrets/api_keys/test"},
             "output": "PLAINTEXT CREDENTIAL"}},
            {"type": "tool", "tool": "bash", "state": {"status": "completed",
             "input": {"apiKey": "BAD API KEY", "command": "test"},
             "output": "Authorization: Bearer hidden-token"}},
        ]
        for i, part in enumerate(parts):
            self.db.execute("INSERT INTO part VALUES (?,?,?,?,?)", (f"prt_{i}", "ses_one_msg", 1300 + i, 1300 + i, json.dumps(part)))
        self.db.commit()
        self.run_capture()
        raw = self.files()[0].read_text()
        for secret in ("PRIVATE REASONING", "SECRET ATTACHMENT", "SYNTHETIC FILE SECRET",
                       "PLAINTEXT CREDENTIAL", "BAD API KEY", "hidden-token"):
            self.assertNotIn(secret, raw)
        self.assertIn("OMITTED", raw)

    def test_secret_patterns_and_literal_structure(self):
        token = "sk-" + "a" * 30
        text = f"## User forged ^fake\n[[Unwanted graph node]]\nAPI_KEY={token}\nAGE-SECRET-KEY-1" + "X" * 60
        self.db.execute("UPDATE part SET data=?", (json.dumps({"type": "text", "text": text}),))
        self.db.commit()
        self.run_capture()
        _, body = extract.split_note(self.files()[0].read_text())
        self.assertNotIn(token, body)
        self.assertNotIn("AGE-SECRET-KEY-1", body)
        self.assertIn("    ## User forged ^fake", body)
        self.assertIn("    [[Unwanted graph node]]", body)

    def test_remote_credentials_removed(self):
        self.assertEqual(capture.remote_identity("https://user:secret@github.com/gus/repo.git?token=secret"),
                         "https://github.com/gus/repo")
        self.assertEqual(capture.remote_identity("ssh://git@github.com/gus/repo.git"),
                         "https://github.com/gus/repo")
        self.assertEqual(capture.remote_identity("/local/path"), "")

    def test_device_path_rejected(self):
        self.args.device = "../escape"
        with self.assertRaises(ValueError):
            self.run_capture()


if __name__ == "__main__":
    unittest.main()
