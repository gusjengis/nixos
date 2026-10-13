"""Offline CLI tests; all writes target temporary vaults."""

import datetime
import fcntl
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

CLI = Path(__file__).with_name("thought-status.py")
spec = importlib.util.spec_from_file_location("thought_status", CLI)
ts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ts)


class ThoughtStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)
        (self.vault / "Thoughts").mkdir()
        self.note = self.vault / "Thoughts/Test.md"
        self.body = b"\nA thought.\r\n\n> Original source\n---\nNo trailing newline"
        self.note.write_bytes(b"---\ntypes: [reflection]\ncustom: keep\n---\n" + self.body)

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, str(CLI), "--vault", str(self.vault), *args],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode == 0, ok, result.stderr)
        return result

    def meta(self):
        return yaml.load(self.note.read_bytes().split(b"---", 2)[1], Loader=ts.Loader)

    def test_unquoted_iso_dates_keep_format_without_global_resolver_changes(self):
        for captured in ("2026-10-06", "2026-10-06T07:08:09Z", "2026-10-06T07:08:09.123400-07:00"):
            with self.subTest(captured=captured):
                line = f"captured: {captured}\n".encode()
                self.note.write_bytes(b"---\ntypes: [reflection]\n" + line + b"---\n" + self.body)
                self.cli("Test")
                self.assertIn(line, self.note.read_bytes())
                self.assertEqual(self.meta()["captured"], captured)
                self.cli("Test", "--reopen")
                self.assertIn(line, self.note.read_bytes())
        self.assertIsInstance(yaml.safe_load("captured: 2026-10-06")["captured"], datetime.date)
        self.assertIn("'2026-10-06'", yaml.safe_dump({"captured": "2026-10-06"}))

    def test_close_and_reopen_with_metadata(self):
        self.note.chmod(0o640)
        self.cli("Thoughts/Test.md", "--reason", "Reviewed", "--resolution", "No further action",
                 "--evidence", "[[Raw/Source]]", "--evidence", "https://example.com")
        meta = self.meta()
        self.assertEqual(meta["status"], "dealt-with")
        self.assertEqual(meta["status-source"], "manual")
        self.assertIsNotNone(datetime.datetime.fromisoformat(meta["status-at"]).tzinfo)
        self.assertEqual(meta["status-reason"], "Reviewed")
        self.assertEqual(meta["resolution"], "No further action")
        self.assertEqual(meta["evidence"], ["[[Raw/Source]]", "https://example.com"])
        self.assertEqual(meta["custom"], "keep")
        self.assertEqual(meta["types"], ["reflection"])
        self.assertTrue(self.note.read_bytes().endswith(b"---\n" + self.body))
        self.assertEqual(self.note.stat().st_mode & 0o777, 0o640)
        self.assertTrue((self.vault / ".note-extract.lock").exists())
        self.cli("Test", "--reopen")
        meta = self.meta()
        self.assertEqual(meta["status"], "todo")
        self.assertEqual(meta["status-source"], "manual")
        self.assertIn("status-at", meta)
        for field in ("status-reason", "resolution", "evidence"):
            self.assertNotIn(field, meta)
        self.assertTrue(self.note.read_bytes().endswith(b"---\n" + self.body))

    def test_reextraction_and_merge_preserve_manual_closure(self):
        extract_path = CLI.parents[4] / "system/hosts/omega/note-extract.py"
        module_spec = importlib.util.spec_from_file_location("lifecycle_extract", extract_path)
        ex = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(ex)
        self.note.write_text("---\ntypes: [idea]\nsource: ['[[Normalized/one]]']\n---\nOriginal idea\n")
        ts.change_status(self.vault, "Test", resolution="implemented", evidence=["[[Sessions/OpenCode/example]]"])
        extractor = ex.Extractor.__new__(ex.Extractor)
        extractor.store = ex.Store(self.vault)
        extractor.extractor = "fixture"
        extractor.db = Mock()
        thought = {"types": ["idea"], "tags": ["notes"], "unclear": False,
                   "text": "Restated old idea", "quote": "Original aspiration", "title": "Test"}
        extractor.refresh("Thoughts/Test", thought, "Normalized/one")
        extractor.merge("Thoughts/Test", thought, "Normalized/two", "2026-10-06", 1.0)
        meta = self.meta()
        self.assertEqual(meta["status"], "dealt-with")
        self.assertEqual(meta["status-source"], "manual")
        self.assertEqual(meta["resolution"], "implemented")
        self.assertEqual(meta["evidence"], ["[[Sessions/OpenCode/example]]"])

    def test_all_types_and_old_statuses_can_be_closed(self):
        for kind in ("task", "reminder", "purchase", "person-action", "idea", "project",
                     "question", "decision", "goal", "resource", "insight", "reflection",
                     "value", "quote", "log", "meta", "noise"):
            for status in ("todo", "done", "dropped", "someday", "none"):
                with self.subTest(kind=kind, status=status):
                    self.note.write_text(f"---\ntypes: [{kind}]\nstatus: {status}\n---\nbody")
                    ts.change_status(self.vault, "Test")
                    self.assertEqual(self.meta()["status"], "dealt-with")

    def test_unsafe_paths_and_invalid_frontmatter_do_not_change_note(self):
        original = self.note.read_bytes()
        for thought in ("", ".", "../Thoughts/Test.md", "Thoughts/../Thoughts/Test.md",
                        str(self.note), "Raw/Test.md", "Missing", "Thoughts"):
            with self.subTest(thought=thought):
                self.cli(thought, ok=False)
                self.assertEqual(self.note.read_bytes(), original)
        for head in (b"No frontmatter", b"---\n[not, mapping]\n---\n",
                     b"---\ninvalid: [\n---\n", b"---\nmissing closing delimiter"):
            self.note.write_bytes(head + self.body)
            self.cli("Test", ok=False)
            self.assertEqual(self.note.read_bytes(), head + self.body)
        self.assertFalse(list(self.note.parent.glob(".thought-status-*")))

    def test_symlinks_rejected(self):
        outside = self.vault / "Outside.md"
        outside.write_bytes(self.note.read_bytes())
        self.note.unlink()
        self.note.symlink_to(outside)
        self.cli("Test", ok=False)
        self.assertNotIn(b"dealt-with", outside.read_bytes())
        self.note.unlink()
        (self.vault / "Thoughts").rmdir()
        folder = self.vault / "Other"
        folder.mkdir()
        (folder / "Test.md").write_bytes(outside.read_bytes())
        (self.vault / "Thoughts").symlink_to(folder, target_is_directory=True)
        self.cli("Test", ok=False)
        self.assertNotIn(b"dealt-with", (folder / "Test.md").read_bytes())

    def test_explicit_lock_waits_before_reading(self):
        lock = self.vault / "shared-lock"
        with lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            process = subprocess.Popen([sys.executable, str(CLI), "--vault", str(self.vault),
                                        "Test", "--lock", str(lock)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                with self.assertRaises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.3)
                self.note.write_bytes(b"---\ntypes: [log]\ncustom: updated\n---\n" + self.body)
                fcntl.flock(handle, fcntl.LOCK_UN)
                _, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stderr)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assertEqual(self.meta()["custom"], "updated")
        self.assertFalse((self.vault / ".note-extract.lock").exists())

    def test_atomic_failure_keeps_original_and_cleans_temp(self):
        original = self.note.read_bytes()
        with patch.object(ts.os, "replace", side_effect=OSError("failed")), self.assertRaises(OSError):
            ts.change_status(self.vault, "Test")
        self.assertEqual(self.note.read_bytes(), original)
        self.assertFalse(list(self.note.parent.glob(".thought-status-*")))

    def test_crlf_body_preserved_and_reopen_options_rejected(self):
        self.note.write_bytes(b"---\r\ntypes: [quote]\r\n---\r\n" + self.body)
        self.cli("Test.md")
        self.assertTrue(self.note.read_bytes().endswith(b"---\r\n" + self.body))
        original = self.note.read_bytes()
        self.cli("Test", "--reopen", "--reason", "Not closure", ok=False)
        self.assertEqual(self.note.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
