import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import contextctl as ctl
import organization as org


class OrganizationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        env = patch.dict(os.environ, {
            "CONTEXT_ROOT": str(self.base / "contexts"),
            "XDG_STATE_HOME": str(self.base / "state"),
            "XDG_RUNTIME_DIR": str(self.base), "HYPRLAND_INSTANCE_SIGNATURE": "test",
        })
        env.start()
        self.addCleanup(env.stop)
        self.a = ctl.create("Projects/Alpha")
        self.b = ctl.create("Beta")
        self.c = ctl.create("Gamma")

    def nodes(self):
        return {node["id"]: node for node in org.resolve(ctl.scan())}

    def test_initial_tree_retains_directory_only_groups(self):
        nodes = self.nodes()
        group = nodes[org.group_id("Projects")]
        self.assertTrue(group["is_group"])
        self.assertEqual(nodes[self.a["id"]]["parent_id"], group["id"])
        self.assertEqual(nodes[self.a["id"]]["breadcrumb"], "Projects / Alpha")
        self.assertFalse(org.layout_path().exists())

    def test_move_rename_open_repository_context_keeps_all_files_and_runtime(self):
        path = ctl.root() / "Projects/Alpha"
        data = ctl.read_json(path / ".context/context.json")
        data["repositories"] = [{"path": "repo"}]
        ctl.atomic_json(path / ".context/context.json", data)
        (path / "repo").mkdir()
        (path / "repo/dirty.txt").write_text("unfinished")
        before = {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}
        ctl.save_state({"mappings": {self.a["id"]: "s1"}, "last_active": self.a["id"]})
        ctl.atomic_json(ctl.runtime_path("hyprland-sessions"), {
            "sessions": [{"id": "s1", "name": "Projects/Alpha"}], "active": "s1"})
        org.change([self.a["id"]], parent=self.b["id"])
        org.change([self.a["id"]], new_label="Focused work")
        node = next(node for node in ctl.catalog()["nodes"] if node["id"] == self.a["id"])
        self.assertEqual(node["breadcrumb"], "Beta / Focused work")
        self.assertEqual(node["runtime_id"], "s1")
        self.assertEqual(before, {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()})
        org.undo()
        org.undo()
        self.assertEqual(self.nodes()[self.a["id"]]["breadcrumb"], "Projects / Alpha")

    def test_batch_subtree_move_and_cycle_rejection(self):
        org.change([self.a["id"]], parent=self.b["id"])
        org.change([self.b["id"], self.a["id"]], parent=self.c["id"])
        self.assertEqual(self.nodes()[self.a["id"]]["breadcrumb"], "Gamma / Beta / Alpha")
        before = org.layout_path().read_bytes()
        with self.assertRaisesRegex(ctl.ContextError, "cycle"):
            org.change([self.c["id"]], parent=self.a["id"])
        self.assertEqual(before, org.layout_path().read_bytes())
        with self.assertRaisesRegex(ctl.ContextError, "cycle"):
            org.change([self.a["id"]], parent=self.a["id"])

    def test_collision_validation_is_case_insensitive(self):
        org.change([self.a["id"]], parent=None)
        with self.assertRaisesRegex(ctl.ContextError, "already exists"):
            org.change([self.b["id"]], new_label="alpha")
        with self.assertRaisesRegex(ctl.ContextError, "already exists"):
            org.create("ALPHA")

    def test_create_same_storage_name_elsewhere_is_unique_and_does_not_open(self):
        identifier = org.create("Beta", parent=self.a["id"])
        node = self.nodes()[identifier]
        self.assertEqual(node["breadcrumb"], "Projects / Alpha / Beta")
        self.assertNotEqual(node["path"], str(ctl.root() / "Beta"))
        self.assertTrue((Path(node["path"]) / ".context/notes/Home.md").exists())
        self.assertFalse(ctl.local_state()["mappings"])

    def test_missing_parent_is_visible_and_remote_edit_blocks_undo(self):
        org.change([self.a["id"]], parent=self.b["id"])
        changed = copy.deepcopy(org.load())
        changed["nodes"][self.a["id"]]["parent_id"] = "not-yet-synced"
        ctl.atomic_json(org.layout_path(), changed)
        node = self.nodes()[self.a["id"]]
        self.assertTrue(node["unplaced"])
        self.assertIsNone(node["parent_id"])
        self.assertFalse(org.can_undo())
        with self.assertRaisesRegex(ctl.ContextError, "elsewhere"):
            org.undo()
        self.assertEqual(org.load(), changed)

    def test_legacy_group_rename_move_and_sync_conflict(self):
        group = org.group_id("Projects")
        org.change([group], new_label="Work")
        org.change([group], parent=self.b["id"])
        self.assertEqual(self.nodes()[self.a["id"]]["breadcrumb"], "Beta / Work / Alpha")
        (ctl.root() / ".context-layout.sync-conflict-20261020-device.json").write_text("{}")
        with self.assertRaisesRegex(ctl.ContextError, "Syncthing conflict"):
            org.change([self.a["id"]], parent=None)

    def test_cli_create_move_rename_undo_and_catalog(self):
        def command(*args):
            result = subprocess.run([sys.executable, "-B", ctl.__file__, *args], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        created = json.loads(command("organize", "create", "Category"))["id"]
        command("organize", "move", self.a["id"], self.b["id"], "--parent", created)
        command("organize", "rename", created, "Broader context")
        catalog = json.loads(command("list"))
        moved = next(node for node in catalog["nodes"] if node["id"] == self.a["id"])
        self.assertEqual(moved["breadcrumb"], "Broader context / Alpha")
        self.assertTrue(catalog["can_undo"])
        command("organize", "undo")
        self.assertEqual(self.nodes()[created]["label"], "Category")
        command("organize", "undo")
        self.assertEqual(self.nodes()[self.a["id"]]["breadcrumb"], "Projects / Alpha")

    def test_promote_renamed_reparented_legacy_group(self):
        group = org.group_id("Projects")
        org.change([group], new_label="Work")
        org.change([group], parent=self.b["id"])
        org.change([self.c["id"]], parent=group)
        identifier = org.promote(group)
        nodes = self.nodes()
        self.assertNotIn(group, nodes)
        self.assertFalse(nodes[identifier]["is_group"])
        self.assertEqual(nodes[self.a["id"]]["breadcrumb"], "Beta / Work / Alpha")
        self.assertEqual(nodes[self.c["id"]]["breadcrumb"], "Beta / Work / Gamma")
        self.assertEqual(nodes[identifier]["path"], str(ctl.root() / "Projects"))

    def test_trash_leaf_preserves_files_in_trash_and_clears_layout_undo(self):
        directory = ctl.root() / "Projects/Alpha"
        (directory / "unfinished.txt").write_text("Keep this work")
        org.change([self.a["id"]], new_label="Focused work")
        trash = self.base / "trash"
        trash.mkdir()

        def move_to_trash(command, **kwargs):
            self.assertEqual(command[:3], ["gio", "trash", "--"])
            path = Path(command[-1])
            path.rename(trash / path.name)
            return SimpleNamespace(returncode=0, stderr="")

        with patch.object(ctl, "clients", return_value=[]), patch.object(org.subprocess, "run", side_effect=move_to_trash):
            org.trash_contexts([self.a["id"]])
        self.assertFalse(directory.exists())
        self.assertEqual((trash / "Alpha/unfinished.txt").read_text(), "Keep this work")
        self.assertTrue((trash / "Alpha/.context/context.json").is_file())
        self.assertNotIn(self.a["id"], self.nodes())
        self.assertFalse(org.can_undo())
        (trash / "Alpha").rename(directory)
        self.assertEqual(self.nodes()[self.a["id"]]["label"], "Focused work")

    def test_trash_rejects_children_and_running_contexts_before_batch_changes(self):
        org.change([self.a["id"]], parent=self.b["id"])
        with patch.object(org.subprocess, "run") as run:
            with self.assertRaisesRegex(ctl.ContextError, "Move children"):
                org.trash_contexts([self.b["id"]])
            ctl.save_state({"mappings": {self.c["id"]: "s1"}, "last_active": None})
            ctl.atomic_json(ctl.runtime_path("hyprland-sessions"), {"sessions": [{"id": "s1", "name": "Gamma"}], "active": "s1"})
            with self.assertRaisesRegex(ctl.ContextError, "Close running"):
                org.trash_contexts([self.a["id"], self.c["id"]])
            run.assert_not_called()
        self.assertTrue((ctl.root() / "Projects/Alpha").is_dir())

    def test_trash_rejects_unrelated_physical_descendants(self):
        parent = ctl.create("Outer")
        child = ctl.create("Outer/Inner")
        org.change([child["id"]], parent=None)
        with self.assertRaisesRegex(ctl.ContextError, "contains other contexts"):
            org.trash_contexts([parent["id"]])
        self.assertTrue((ctl.root() / "Outer/Inner/.context/context.json").is_file())

    def test_trash_failure_preserves_context_and_cli_requires_confirmation(self):
        with patch.object(ctl, "clients", return_value=[]), patch.object(org.subprocess, "run", return_value=SimpleNamespace(returncode=1, stderr="Trash unavailable")):
            with self.assertRaisesRegex(ctl.ContextError, "Trash unavailable"):
                org.trash_contexts([self.a["id"]])
        self.assertIn(self.a["id"], self.nodes())
        result = subprocess.run([sys.executable, "-B", ctl.__file__, "organize", "delete", self.a["id"]], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--confirm", result.stderr)
        self.assertTrue((ctl.root() / "Projects/Alpha/.context/context.json").is_file())


if __name__ == "__main__":
    unittest.main()
