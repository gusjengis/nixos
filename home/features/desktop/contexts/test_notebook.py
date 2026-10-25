import json
import os
import tempfile
import unittest
from pathlib import Path

import notebook
import yaml


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)

    def note(self, name, text):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def test_migration_preserves_body_comments_status_and_created(self):
        path = self.note("Job.md", '---\n# keep this\nstatus: In-Progress\ncreated: "2020-01-01T00:00:00Z"\ncustom: [one, two]\n---\n\nBody [[link]]\n')
        notebook.setup(self.vault)
        text = path.read_text()
        _, value, _ = notebook.fields(text)
        self.assertTrue(text.endswith("---\n\nBody [[link]]\n"))
        self.assertIn("# keep this", text)
        self.assertEqual(value["status"], "In-Progress")
        self.assertEqual(value["created"], "2020-01-01T00:00:00Z")
        self.assertEqual(value["custom"], ["one", "two"])
        self.assertEqual(value["kanban-history"][0]["event"], "observed")
        before = path.stat().st_mtime_ns
        notebook.setup(self.vault, force=True)
        self.assertEqual(before, path.stat().st_mtime_ns)

    def test_aliases_missing_status_and_creation_estimates(self):
        for index, status in enumerate((None, "Ideas", "Outstanding Questions", "Done")):
            path = self.note(f"Note {index}.md", f"---\nstatus: {status}\n---\nBody" if status else "Body")
            os.utime(path, (1600000000, 1600000000))
        notebook.setup(self.vault)
        for index in range(4):
            _, value, _ = notebook.fields((self.vault / f"Note {index}.md").read_text())
            self.assertEqual(value["status"], "Done" if index == 3 else "Thoughts")
            self.assertEqual(value["created"], "2020-09-13T12:26:40.000Z")
            self.assertIn("estimate", value["created-source"])

    def test_home_scaffolding_trashed_content_retained_and_support_excluded(self):
        self.note("Home.md", "# Alpha\n\n## Now\n\n## Next\n\n- [ ] \n\n## Working Notes\n\n## Return Point\n")
        meaningful = self.note("Home.md.md", "Important [[roadmap]]\n")
        template = self.note("Templates/Note.md", "Template body")
        support = self.note("Guide.md", "---\nkanban: false\n---\nGuide")
        notebook.setup(self.vault)
        self.assertFalse(meaningful.exists())
        self.assertTrue((self.vault / ".trash/Home.md").exists())
        self.assertTrue((self.vault / "Notebook Notes.md").read_text().endswith("Important [[roadmap]]\n"))
        self.assertEqual(template.read_text(), "Template body")
        self.assertEqual(support.read_text(), "---\nkanban: false\n---\nGuide")

    def test_settings_and_existing_views_preserved(self):
        self.note(".obsidian/app.json", '{"custom":true,"newFileLocation":"current"}')
        self.note(".obsidian/community-plugins.json", '["existing-plugin"]')
        self.note(".obsidian/core-plugins.json", '["file-explorer"]')
        self.note("Project Board.base", "custom view")
        notebook.setup(self.vault)
        config = self.vault / ".obsidian"
        self.assertEqual(json.loads((config / "app.json").read_text()), {"custom": True, "newFileLocation": "root"})
        self.assertEqual(json.loads((config / "community-plugins.json").read_text()), ["existing-plugin", "context-notebook"])
        self.assertEqual(json.loads((config / "core-plugins.json").read_text()), ["file-explorer", "bases"])
        self.assertTrue((config / "plugins/context-notebook").is_symlink())
        self.assertEqual((self.vault / "Project Board.base").read_text(), "custom view")
        board = yaml.safe_load((self.vault / "Kanban.base").read_text())
        self.assertEqual(board["views"][0]["groupOrder"], list(notebook.PHASES))
        self.assertEqual(board["views"][0]["groupBy"]["property"], "status")

    def test_block_history_update_preserves_following_metadata(self):
        path = self.note("Existing.md", '---\nstatus: Done\nkanban-history:\n  - status: Todo\n    at: "2026-01-01T00:00:00Z"\n    event: entered\ncustom: keep\n---\nBody\n')
        notebook.setup(self.vault)
        _, value, _ = notebook.fields(path.read_text())
        self.assertEqual(value["custom"], "keep")
        self.assertEqual([entry["status"] for entry in value["kanban-history"]], ["Todo", "Done"])
        self.assertTrue(path.read_text().endswith("---\nBody\n"))

    def test_crlf_body_is_preserved_exactly(self):
        path = self.vault / "Windows note.md"
        body = b"Line one\r\n\r\nLine two\r\n"
        path.write_bytes(b"---\r\nstatus: Ideas\r\n---\r\n" + body)
        notebook.setup(self.vault)
        self.assertTrue(path.read_bytes().endswith(b"---\r\n" + body))

    def test_unknown_status_does_not_silently_hide_card_or_remove_home(self):
        self.note("Home.md", "# Alpha\n")
        original = "---\nstatus: Custom phase\n---\nKeep me"
        path = self.note("Custom.md", original)
        with self.assertRaisesRegex(notebook.ctl.ContextError, "Unknown Kanban"):
            notebook.setup(self.vault)
        self.assertEqual(path.read_text(), original)
        self.assertTrue((self.vault / "Home.md").exists())

    def test_profile_seed_retains_unrelated_storage_and_obeys_lock(self):
        import plyvel
        profile = self.vault / "profile"
        notebook.enable_profile(profile, "1234567890abcdef")
        storage = profile / "Local Storage/leveldb"
        with plyvel.DB(str(storage)) as database:
            key = b"_app://obsidian.md\x00\x01enable-plugin-1234567890abcdef"
            self.assertEqual(database.get(key), b"\x01true")
            database.put(b"unrelated", b"keep")
            with self.assertRaisesRegex(notebook.ctl.ContextError, "Close the context notebook"):
                notebook.enable_profile(profile, "1234567890abcdef")
        notebook.enable_profile(profile, "1234567890abcdef")
        with plyvel.DB(str(storage)) as database:
            self.assertEqual(database.get(b"unrelated"), b"keep")


if __name__ == "__main__":
    unittest.main()
