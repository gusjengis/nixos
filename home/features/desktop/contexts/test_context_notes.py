import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import context_notes as api
import contextctl as ctl
import notebook


class ContextNotesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "CONTEXT_ROOT": str(self.base / "contexts"), "XDG_STATE_HOME": str(self.base / "state"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.first = ctl.create("First", "/etc/nixos")
        self.second = ctl.create("Second", "/etc/nixos")
        self.vault = api.resolve(self.first["id"])

    def test_owner_not_cwd_or_visible_context_and_no_fallback(self):
        self.vault.create({"title": "My work", "body": "First context"})
        self.assertEqual(api.resolve(self.second["id"]).listing({})["total"], 0)
        with self.assertRaisesRegex(ctl.ContextError, "No owning"):
            api.resolve(None)
        with self.assertRaisesRegex(ctl.ContextError, "unavailable"):
            api.resolve("missing")

    def test_cli_dispatches_all_read_actions_and_write_roundtrip(self):
        def command(action, request):
            output = io.StringIO()
            with patch("sys.stdin", io.StringIO(json.dumps(request))), patch("sys.stdout", output):
                self.assertEqual(api.main(["--context", self.first["id"], action]), 0)
            return json.loads(output.getvalue())

        created = command("create", {"title": "Dictation", "body": "Originating context."})
        self.assertEqual(command("info", {})["context_id"], self.first["id"])
        self.assertEqual(command("brief", {})["counts"]["Thoughts"], 1)
        self.assertEqual(command("list", {})["total"], 1)
        self.assertEqual(command("search", {"query": "dictation"})["notes"][0]["path"], "Dictation.md")
        current = command("read", {"path": created["path"]})
        updated = command("update", {"path": current["path"], "revision": current["revision"], "status": "Todo"})
        self.assertEqual(updated["status"], "Todo")

    def test_offline_creation_transitions_reentry_and_noop(self):
        card = self.vault.create({"title": "Context-aware dictation", "body": "User's thought.\n"})
        _, original, _ = notebook.fields(card["content"])
        for phase in ("Todo", "In-Progress", "Todo", "Done"):
            card = self.vault.update({"path": card["path"], "revision": card["revision"], "status": phase})
        _, metadata, _ = notebook.fields(card["content"])
        self.assertEqual(metadata["created"], original["created"])
        self.assertEqual(metadata["created-source"], "agent-create")
        self.assertEqual([event["status"] for event in metadata["kanban-history"]],
                         ["Thoughts", "Todo", "In-Progress", "Todo", "Done"])
        self.assertTrue(all(event["event"] == "entered" for event in metadata["kanban-history"]))
        self.assertTrue(card["content"].endswith("User's thought.\n"))
        path = self.vault.path(card["path"])
        before = path.stat().st_mtime_ns
        self.vault.update({"path": card["path"], "revision": card["revision"], "status": "Done"})
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_open_card_targets_own_profile_and_rejects_stale_context(self):
        from urllib.parse import parse_qs, urlparse

        card = self.vault.create({"title": "A & B #1", "body": "Keep this"})
        item = dict(self.first, runtime_id="s2")
        with patch.object(ctl, "launch_context", return_value=item), \
                patch.object(ctl, "notes") as notes, patch.object(ctl, "spawn") as spawn, \
                patch.object(ctl, "evaluate") as evaluate:
            self.vault.open({"path": card["path"]})
            notes.assert_called_once_with("s2")
            arguments = spawn.call_args.args[0]
            self.assertIn(f"--user-data-dir={ctl.state_root() / 'obsidian' / self.first['id']}", arguments)
            self.assertEqual(parse_qs(urlparse(arguments[-1]).query)["path"],
                             [str(self.vault.directory / card["path"])])
            evaluate.assert_called_once_with("require('sessions').show_special('notes')")
        with patch.object(ctl, "launch_context", return_value=self.second), \
                patch.object(ctl, "spawn") as spawn:
            with self.assertRaisesRegex(ctl.ContextError, "Active context changed"):
                self.vault.open({"path": card["path"]})
            spawn.assert_not_called()

    def test_manual_changes_win_over_stale_agent(self):
        card = self.vault.create({"title": "Widget", "body": "My original thought."})
        path = self.vault.path(card["path"])
        manual = notebook.edit_fields(card["content"], {"status": "Todo"}) + "\nNew user detail.\n"
        path.write_text(manual)
        with self.assertRaisesRegex(ctl.ContextError, "changed since read"):
            self.vault.update({"path": card["path"], "revision": card["revision"], "status": "Done"})
        self.assertEqual(path.read_text(), manual)
        current = self.vault.read({"path": card["path"]})
        updated = self.vault.update({"path": card["path"], "revision": current["revision"], "work_state": "Next: margin layout."})
        self.assertEqual(updated["status"], "Todo")
        self.assertIn("New user detail.", updated["content"])
        _, metadata, _ = notebook.fields(updated["content"])
        self.assertEqual(metadata["kanban-history"][-1]["event"], "observed")

    def test_work_state_replaces_only_owned_section(self):
        card = self.vault.create({"title": "Desktop widget", "body": "User's wording.\n\n## My notes\nKeep this.\n\n"})
        original = card["content"]
        card = self.vault.update({"path": card["path"], "revision": card["revision"], "work_state": "Next: render active cards."})
        self.assertTrue(card["content"].startswith(original))
        card = self.vault.update({"path": card["path"], "revision": card["revision"], "work_state": "Next: verify context switching."})
        self.assertEqual(card["content"].count(api.START), 1)
        self.assertNotIn("render active cards", card["content"])
        self.assertIn("Keep this.", card["content"])

    def test_yaml_timestamp_history_remains_iso8601(self):
        path = self.vault.directory / "Existing.md"
        path.write_text("---\nstatus: Todo\ncreated: 2026-01-01T00:00:00Z\nkanban-history:\n"
                        "  - status: Todo\n    at: 2026-01-01T00:00:00Z\n    event: entered\n---\nUser text")
        card = self.vault.read({"path": "Existing.md"})
        card = self.vault.update({"path": card["path"], "revision": card["revision"], "status": "In-Progress"})
        _, value, _ = notebook.fields(card["content"])
        self.assertEqual(value["kanban-history"][0]["at"], "2026-01-01T00:00:00Z")
        self.assertIn("created: 2026-01-01T00:00:00Z", card["content"])

    def test_duplicate_creation_excluded_notes_and_traversal(self):
        self.vault.create({"title": "Existing", "body": "Keep"})
        with self.assertRaises(FileExistsError):
            self.vault.create({"title": "Existing", "body": "Overwrite"})
        self.assertTrue(self.vault.read({"path": "Existing.md"})["content"].endswith("Keep"))
        for name in ("../escape.md", "/tmp/escape.md", ".obsidian/config.md", "Kanban.base", "Templates/Raw.md"):
            with self.subTest(name=name), self.assertRaises(ctl.ContextError):
                self.vault.read({"path": name})
        path = self.vault.directory / "Support.md"
        path.write_text("---\nkanban: false\n---\nSupport")
        self.assertEqual(self.vault.listing({})["total"], 1)

    def test_bounded_briefing_search_and_pagination_without_note_limit(self):
        for index in range(85):
            self.vault.create({"title": f"Thought {index:03} about a meaningful subject", "body": "detail " * 200})
        active = self.vault.create({"title": "Context-aware dictation", "body": "Capture belongs to the originating context.", "status": "In-Progress"})
        self.vault.update({"path": active["path"], "revision": active["revision"], "work_state": "Next: capture UUID on recording start."})
        brief = self.vault.brief("dictation")
        self.assertLessEqual(len(json.dumps(brief, ensure_ascii=False)), 5000)
        self.assertEqual(brief["counts"]["Thoughts"], 85)
        self.assertGreater(brief["omitted"], 0)
        self.assertEqual(brief["notes"][0]["title"], "Context-aware dictation")
        self.assertIn("Next:", brief["notes"][0]["return_point"])
        results = self.vault.listing({"query": "recording"})
        self.assertEqual(results["notes"][0]["path"], "Context-aware dictation.md")
        page = self.vault.listing({})
        self.assertIsNotNone(page["next_offset"])
        page2 = self.vault.listing({"offset": page["next_offset"]})
        self.assertNotEqual(page["notes"][0], page2["notes"][0])

    def test_handoff_return_points_visible_before_thought_backlog(self):
        for index in range(50):
            self.vault.create({"title": f"A thought {index:03}", "body": "An idea."})
        card = self.vault.create({"title": "Agent notebook integration", "body": "Keep notes current.", "status": "Done"})
        self.vault.update({"path": card["path"], "revision": card["revision"],
                           "work_state": "Next: desktop In-Progress widget."})
        brief = self.vault.brief()
        self.assertEqual(brief["notes"][0]["title"], "Agent notebook integration")
        self.assertEqual(brief["notes"][0]["return_point"], "Next: desktop In-Progress widget.")


if __name__ == "__main__":
    unittest.main()
