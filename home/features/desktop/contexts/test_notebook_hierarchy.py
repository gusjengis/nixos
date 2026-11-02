import io
import json
import os
import shutil
import subprocess
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import context_notes
import contextctl as ctl
import notebook
import notebook_hierarchy as hierarchy
import organization as org
import yaml


class NotebookHierarchyTests(unittest.TestCase):
    def setUp(self):
        display = os.environ.get("WAYLAND_DISPLAY", "")
        self.wayland_display = (display if display.startswith("/") else
                                str(Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000")) / display))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        environment = patch.dict(os.environ, {
            "CONTEXT_ROOT": str(self.base / "contexts"),
            "XDG_STATE_HOME": str(self.base / "state"),
            "XDG_RUNTIME_DIR": str(self.base), "HYPRLAND_INSTANCE_SIGNATURE": "notebook-test",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.parent = ctl.create("Parent")
        self.child = ctl.create("Child")
        self.grandchild = ctl.create("Grandchild")
        org.change([self.child["id"]], parent=self.parent["id"])
        org.change([self.grandchild["id"]], parent=self.child["id"])

    def vault(self, context):
        return Path(ctl.selected_context(context["id"])["path"]) / ".context/notes"

    def reconcile(self):
        self.assertEqual(ctl.reconcile_notebooks(), [])

    def test_immediate_links_recursive_api_owner_locks_and_local_view(self):
        self.reconcile()
        parent, child, grandchild = map(self.vault, (self.parent, self.child, self.grandchild))
        self.assertTrue((parent / "Child").is_symlink())
        self.assertFalse((parent / "Grandchild").exists())
        self.assertEqual((parent / "Child/Grandchild").resolve(), grandchild)
        self.assertFalse(os.readlink(parent / "Child").startswith("/"))
        original = context_notes.resolve(self.grandchild["id"]).create({"title": "Same title", "body": "Original body"})
        api = context_notes.resolve(self.parent["id"])
        api.create({"title": "Same title", "body": "Parent body"})
        self.assertEqual(api.listing({"local_only": True})["total"], 1)
        rows = api.listing({})["notes"]
        self.assertEqual(len(rows), 2)
        global_api = context_notes.resolve("global")
        global_rows = global_api.listing({})["notes"]
        self.assertEqual(len(global_rows), 2)
        self.assertEqual({row["path"] for row in global_rows}, {"Parent/Same title.md", "Parent/Child/Grandchild/Same title.md"})
        nested = next(row for row in rows if row["owner_context_id"] == self.grandchild["id"])
        self.assertEqual(nested["context"], "Parent / Child / Grandchild")
        self.assertEqual(nested["owner_path"], "Same title.md")
        self.assertEqual(nested["path"], "Child/Grandchild/Same title.md")
        card = api.read({"path": nested["path"]})
        updated = api.update({"path": nested["path"], "revision": card["revision"], "status": "Done"})
        self.assertEqual(updated["path"], nested["path"])
        self.assertTrue((child / "Grandchild").is_symlink())
        owner = context_notes.resolve(self.grandchild["id"]).read({"path": "Same title.md"})
        self.assertEqual(owner["status"], "Done")
        self.assertTrue(owner["content"].endswith("Original body"))
        with self.assertRaisesRegex(ctl.ContextError, "changed since read"):
            api.update({"path": nested["path"], "revision": original["revision"], "status": "Todo"})
        board = yaml.safe_load((parent / "Kanban.base").read_text())
        self.assertIn("Parent / Child / Grandchild", board["formulas"]["Context"])
        self.assertEqual(board["views"][-1]["name"], "This context")
        self.assertIn('!file.inFolder("Child")', board["views"][-1]["filters"]["and"])
        files = [parent / "Kanban.base", parent / hierarchy.MANIFEST, parent / "Child"]
        mtimes = [path.lstat().st_mtime_ns for path in files]
        self.reconcile()
        self.assertEqual(mtimes, [path.lstat().st_mtime_ns for path in files])

    def test_global_notebook_has_independent_profile_and_explicit_open(self):
        with patch.object(ctl, "clients", return_value=[]), \
                patch.object(notebook, "enable_profile"), patch.object(ctl, "spawn") as spawn, \
                patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(ctl.main(["notes", "--global"]), 0)
        profile = ctl.state_root() / "obsidian" / hierarchy.GLOBAL_ID
        self.assertIn(f"--user-data-dir={profile}", spawn.call_args.args[0])
        self.assertEqual(next(iter(ctl.read_json(profile / "obsidian.json")["vaults"].values()))["path"],
                         str(ctl.root() / ".context/notes"))
        self.assertFalse((ctl.root() / ".context/context.json").exists())

    def test_cli_create_rename_move_undo_and_incoming_layout(self):
        def command(*arguments):
            with patch.object(ctl, "snapshot", return_value={"sessions": [], "active": None}), \
                    patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(ctl.main(list(arguments)), 0)
                return output.getvalue()

        self.reconcile()
        parent, child, grandchild = map(self.vault, (self.parent, self.child, self.grandchild))
        created = json.loads(command("organize", "create", "New child", "--parent", self.child["id"]))
        self.assertTrue((child / "New child").is_symlink())
        command("organize", "rename", self.child["id"], "Renamed")
        self.assertFalse((parent / "Child").exists())
        self.assertEqual((parent / "Renamed/Grandchild").resolve(), grandchild)
        command("organize", "move", self.grandchild["id"], "--parent", self.parent["id"])
        self.assertFalse((child / "Grandchild").exists())
        self.assertEqual((parent / "Grandchild").resolve(), grandchild)
        command("organize", "undo")
        self.assertEqual((parent / "Renamed/Grandchild").resolve(), grandchild)
        # Simulate a synced layout arriving without a local organizer command.
        layout = org.load()
        layout["nodes"][created["id"]]["label"] = "Incoming label"
        ctl.atomic_json(org.layout_path(), layout)
        self.reconcile()
        self.assertTrue((child / "Incoming label").is_symlink())
        self.assertFalse((child / "New child").exists())

    def test_collisions_user_files_and_modified_links_are_preserved(self):
        parent = self.vault(self.parent)
        collision = parent / "Child"
        collision.mkdir()
        (collision / "Keep.md").write_text("User work")
        errors = ctl.reconcile_notebooks()
        self.assertTrue(any("collision" in error for error in errors))
        self.assertEqual((collision / "Keep.md").read_text(), "User work")
        (collision / "Keep.md").unlink()
        collision.rmdir()
        self.reconcile()
        collision.unlink()
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        collision.symlink_to(elsewhere, target_is_directory=True)
        org.change([self.child["id"]], new_label="New name")
        self.reconcile()
        self.assertEqual(collision.resolve(), elsewhere)
        self.assertTrue((parent / "New name").is_symlink())

    def test_moved_child_and_arbitrary_links_cannot_redirect_agent_writes(self):
        self.reconcile()
        original = context_notes.resolve(self.child["id"]).create({"title": "Work", "body": "Keep"})
        api = context_notes.resolve(self.parent["id"])
        org.change([self.child["id"]], parent=None)
        with self.assertRaisesRegex(ctl.ContextError, "moved"):
            api.update({"path": "Child/Work.md", "revision": original["revision"], "status": "Done"})
        (self.vault(self.parent) / "Unknown").symlink_to(self.vault(self.child), target_is_directory=True)
        with self.assertRaises(ctl.ContextError):
            api.read({"path": "Unknown/Work.md"})
        self.assertEqual(context_notes.resolve(self.child["id"]).read({"path": "Work.md"})["status"], "Thoughts")

    def test_old_alias_is_rejected_after_move_within_same_ancestor(self):
        other = ctl.create("Other child")
        org.change([other["id"]], parent=self.parent["id"])
        self.reconcile()
        context_notes.resolve(self.child["id"]).create({"title": "Work", "body": "Original"})
        org.change([self.child["id"]], parent=other["id"])
        with self.assertRaisesRegex(ctl.ContextError, "moved"):
            context_notes.resolve(self.parent["id"]).read({"path": "Child/Work.md"})

    def test_directory_only_groups_and_custom_board_settings(self):
        grouped = ctl.create("Group/Deep")
        group_id = org.group_id("Group")
        org.change([group_id], parent=self.parent["id"])
        parent = self.vault(self.parent)
        board = yaml.safe_load((parent / "Kanban.base").read_text())
        board["views"][0]["columnWidth"] = 333
        notebook.write(parent / "Kanban.base", yaml.safe_dump(board))
        self.reconcile()
        self.assertFalse((parent / "Group").is_symlink())
        self.assertEqual((parent / "Group/Deep").resolve(), self.vault(grouped))
        self.assertEqual(yaml.safe_load((parent / "Kanban.base").read_text())["views"][0]["columnWidth"], 333)
        org.change([group_id], parent=None)
        self.reconcile()
        self.assertFalse((parent / "Group").exists())

    @unittest.skipUnless(os.environ.get("NOTEBOOK_NATIVE_TESTS") == "1" and shutil.which("qs"), "opt-in native QuickShell fixture")
    def test_nested_widget_model_pagination_and_context_isolation(self):
        empty = ctl.create("Empty")
        api = context_notes.resolve(self.child["id"])
        for index in range(90):
            api.create({"title": f"Active {index:03}", "body": "Child work", "status": "In-Progress"})
        api.create({"title": "Next", "body": "Child todo", "status": "Todo"})
        self.reconcile()
        environment = dict(os.environ, QT_QPA_PLATFORM="wayland", WAYLAND_DISPLAY=self.wayland_display,
                           TEST_CONTEXT_FIRST=self.parent["id"],
                           TEST_CONTEXT_SECOND=empty["id"], TEST_CONTEXT_CHILD=self.child["id"])
        result = subprocess.run(["qs", "-p", str(Path(__file__).parent.parent / "quickshell/test_in_progress.qml")],
                                capture_output=True, text=True, timeout=25, env=environment)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: In-Progress", result.stdout + result.stderr)
        self.assertNotIn("FAILED:", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
