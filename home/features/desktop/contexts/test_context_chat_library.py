"""Ownership/scoping contracts plus opt-in native portable-library round trips."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from unittest.mock import Mock, patch

import context_chat_library as library
import contextctl as ctl
import organization
import persistence
from test_chat_portability import IsolatedChatTest, native_fixture


class ScopeTests(IsolatedChatTest):
    def setUp(self):
        super().setUp()
        os.environ["CONTEXT_ROOT"] = str(self.base / "contexts")
        self.work = self.base / "repo"
        self.work.mkdir()
        self.parent = ctl.create("NixOS", str(self.work))
        self.child = ctl.create("Context", str(self.work))
        self.sibling = ctl.create("Theme", str(self.work))
        self.other = ctl.create("Other", str(self.base / "offline"))
        self.grandchild = ctl.create("Nested", str(self.work))
        organization.change([self.child["id"], self.sibling["id"], self.other["id"]], parent=self.parent["id"])
        organization.change([self.grandchild["id"]], parent=self.other["id"])

    def visible(self, item):
        contexts = ctl.scan()
        return {context["id"] for context in library.visible_contexts(ctl.find_context(item["id"]), contexts)}

    def test_scope_uses_logical_descendants_and_configured_roots(self):
        self.assertEqual(self.visible(self.parent), {item["id"] for item in (self.parent, self.child, self.sibling, self.grandchild)})
        self.assertEqual(self.visible(self.child), {self.child["id"]})
        # Intervening different-workdir context does not erase matching deeper descendants.
        self.assertEqual(self.visible(self.other), {self.other["id"]})
        with patch.object(library, "native_rows", side_effect=AssertionError("Watcher must not touch SQLite")):
            library.refresh_scopes(ctl.scan())
        scope = ctl.read_json(library.scope_path(ctl.find_context(self.parent["id"]), library.database_path()))
        self.assertEqual(set(scope["ids"]), self.visible(self.parent))
        organization.change([self.child["id"]], parent=None)
        library.refresh_scopes(ctl.scan())
        self.assertNotIn(self.child["id"], ctl.read_json(library.scope_path(ctl.find_context(self.parent["id"]), library.database_path()))["ids"])

    def test_missing_targets_do_not_match_via_fallback_and_symlinks_match(self):
        with ctl.mutation_lock():
            ctl.set_working_directory(self.parent["id"], str(self.base / "missing-a"))
            ctl.set_working_directory(self.child["id"], str(self.base / "missing-b"))
        self.assertEqual(self.visible(self.parent), {self.parent["id"]})
        alias = self.base / "repo-link"
        alias.symlink_to(self.work, target_is_directory=True)
        ctl.set_working_directory(self.parent["id"], str(alias))
        ctl.set_working_directory(self.child["id"], str(self.work))
        self.assertIn(self.child["id"], self.visible(self.parent))

    def test_busy_library_defers_without_blocking_other_contexts_or_watcher(self):
        database = self.base / "fixture.db"
        database.touch()
        contexts = ctl.scan()
        calls = []

        def capture(context, _database, hydrate=False):
            calls.append(context["id"])
            if context["id"] == self.child["id"]:
                raise library.chats.ChatChangedDuringCheckpoint("busy")
        errors = []
        with patch.object(library, "sync_context", side_effect=capture), patch.object(library, "publish_scopes"):
            library.sync_all(contexts, database, errors=errors)
        self.assertEqual(set(calls), {item["id"] for item in contexts})
        self.assertEqual([identifier for identifier, _error in errors], [self.child["id"]])
        with library.library_lock(), patch.object(library, "publish_scopes", side_effect=AssertionError("Watcher must defer")):
            library.refresh_scopes(contexts)

    @unittest.skipUnless(shutil.which("tmux"), "tmux unavailable")
    def test_launcher_uses_tmux_owner_despite_shared_cwd_and_stale_environment(self):
        tmux_socket = self.base / "identity.sock"

        def tmux(*args):
            return subprocess.run(["tmux", "-S", str(tmux_socket), *args], check=True, text=True, capture_output=True).stdout.strip()
        child = ctl.find_context(self.child["id"])
        tmux("new-session", "-d", "-s", "fixture", "-e", "CONTEXT_DIRECTORY=" + child["path"], "-c", str(self.work), "sleep 60")
        self.addCleanup(lambda: subprocess.run(["tmux", "-S", str(tmux_socket), "kill-server"], check=False, capture_output=True))
        pane = tmux("list-panes", "-t", "fixture", "-F", "#{pane_id}")
        probe = self.base / "identity.py"
        probe.write_text('import json,os; print(json.dumps({key:os.environ.get(key) for key in ("CONTEXT_ID","CONTEXT_DIRECTORY")}))')
        env = dict(os.environ, TMUX=f"{tmux_socket},123,0", TMUX_PANE=pane,
                   CONTEXT_DIRECTORY=ctl.find_context(self.parent["id"])["path"])
        env.pop("OPENCODE_CONTEXT_HELPER", None)
        result = subprocess.run([sys.executable, "-B", library.__file__, "launch", sys.executable, str(probe)],
                                cwd=self.work, env=env, text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), {"CONTEXT_ID": self.child["id"], "CONTEXT_DIRECTORY": child["path"]})


@unittest.skipUnless(os.environ.get("PERSISTENCE_NATIVE_TESTS") == "1", "set PERSISTENCE_NATIVE_TESTS=1")
class NativeLibraryTests(ScopeTests):
    def setUp(self):
        super().setUp()
        self.fixture = native_fixture(self.work)
        (self.work / "external.txt").write_text("portable attachment")
        (self.work / "result.txt").write_text("portable result")
        self.sid = self.fixture["info"]["id"]
        self.fixture["info"]["metadata"] = {"desktop_context": {
            "id": self.child["id"], "chat": self.sid, "session": self.sid}}
        self.import_chat(self.fixture)

    def import_chat(self, data):
        file = self.base / "native-import.json"
        file.write_text(json.dumps(data))
        library.chats._cli(["import", str(file)], str(self.work))

    def child_context(self):
        return ctl.find_context(self.child["id"])

    def edit_title(self, sid, title):
        # Fixture-only native projection mutation; production always uses native APIs.
        with closing(sqlite3.connect(library.database_path())) as db, db:
            db.execute("UPDATE session SET title=?, time_updated=time_updated+1000 WHERE id=?", (title, sid))

    def index(self):
        archive = library.storage(self.child_context())
        return archive, archive.load()

    def test_all_owned_chats_saved_without_open_panes_and_parent_only_references(self):
        second = {"info": dict(self.fixture["info"], id="ses_otherconversation", title="Second"), "messages": []}
        second["info"]["metadata"] = {"desktop_context": {"id": self.child["id"], "chat": second["info"]["id"], "session": second["info"]["id"]}}
        self.import_chat(second)
        library.sync_all()
        archive, current = self.index()
        index = json.loads((archive.view(current) / "index.json").read_bytes())
        self.assertEqual(set(index["chats"]), {self.sid, second["info"]["id"]})
        reference = library.reference({"session_id": self.sid, "database": str(library.database_path())})
        self.assertEqual(reference, {"owner": self.child["id"], "chat": self.sid, "member": self.sid})
        self.assertFalse(library.storage(ctl.find_context(self.parent["id"])).directory.exists())
        before = current["id"]
        library.sync_all()
        self.assertEqual(self.index()[1]["id"], before)
        self.assertEqual(library.restore_reference(reference)[0], self.sid)

    def test_move_context_and_external_work_root_then_resume_from_parent(self):
        library.sync_all()
        original = self.child_context()
        moved = self.base / "moved-contexts"
        shutil.copytree(ctl.root(), moved)
        self.environment("destination")
        os.environ["CONTEXT_ROOT"] = str(moved)
        new_work = self.base / "new-repo"
        shutil.copytree(self.work, new_work)
        self.work = new_work
        for item in (self.child, self.parent):
            ctl.set_working_directory(item["id"], str(new_work))
        # Initialize a genuinely separate native index; keep an unrelated chat intact.
        unowned = {"info": dict(self.fixture["info"], id="ses_unowned", directory=str(new_work)), "messages": []}
        unowned["info"].pop("metadata")
        self.import_chat(unowned)
        visible = library.visible_contexts(ctl.find_context(self.parent["id"]), ctl.scan())
        library.sync_all(hydrate=True, only={item["id"] for item in visible})
        reference = {"owner": self.child["id"], "chat": self.sid, "member": self.sid}
        sid, directory = library.restore_reference(reference)
        self.assertEqual(directory, str(new_work))
        exported = library.chats._export(sid, directory)
        self.assertEqual(exported["info"]["metadata"]["desktop_context"]["id"], self.child["id"])
        self.assertEqual(exported["messages"][1]["info"]["path"]["cwd"], str(new_work))
        before = self.index()[1]["id"]
        library.sync_all(hydrate=True)
        self.assertEqual(self.index()[1]["id"], before, "Import must not republish relocated machine IDs/paths")
        # Resume/update while viewing from parent; bytes still publish only to child.
        self.edit_title(sid, "Updated through parent")
        library.sync_all()
        self.assertNotEqual(self.index()[1]["id"], before)
        self.assertFalse(library.storage(ctl.find_context(self.parent["id"])).directory.exists())
        self.assertEqual(library.chats._export("ses_unowned", directory)["info"]["title"], unowned["info"]["title"])
        self.assertNotEqual(original["path"], self.child_context()["path"])

    def test_divergent_portable_and_native_edits_preserved(self):
        library.sync_all()
        archive, current = self.index()
        self.edit_title(self.sid, "Local edit")
        # Another device's complete archive publication arrived after our witness.
        tree = library.store.Tree()
        tree.copy_from(archive.view(current))
        index = json.loads(tree.read("index.json"))
        index["chats"][self.sid]["fingerprint"] = "other-device-edit"
        tree.path("index.json").write_bytes(library.store.canonical(index))
        archive.publish(tree, {"device": "other", "context_id": self.child["id"], "warnings": []}, current)
        incoming = archive.load()["id"]
        with self.assertRaisesRegex(ValueError, "divergent"):
            library.sync_all(hydrate=True)
        self.assertEqual(archive.load()["id"], incoming)
        self.assertEqual(library.chats._export(self.sid, str(self.work))["info"]["title"], "Local edit")

    def test_parent_pane_stores_only_child_library_reference_and_restores_subagent(self):
        child_id = "ses_ownedsubagent"
        child = {"info": dict(self.fixture["info"], id=child_id, parentID=self.sid), "messages": []}
        child["info"]["metadata"] = {"desktop_context": {"id": self.child["id"], "chat": self.sid, "session": child_id}}
        self.import_chat(child)
        parent = ctl.find_context(self.parent["id"])
        tree = library.store.Tree()
        pane = {"id": "pane-identity", "command": "opencode", "cwd": persistence.encode_path(str(self.work), parent),
                "local": {"@persistence-chat-socket": "/fixture-chat.sock", "pane_pid": "123", "pane_id": "%0"}}
        selection = {"session_id": child_id, "directory": str(self.work), "database": str(library.database_path())}
        with patch.object(library.chats, "read_selection", return_value=selection):
            persistence.adapter_capture(Mock(socket="/fixture-tmux.sock"), pane, tree.path(), parent, [])
        self.assertNotIn("chat", pane)
        self.assertEqual(tree.files, {}, "Parent terminal checkpoint must not duplicate child chat bytes")
        self.assertEqual(pane["chat_library"], {"owner": self.child["id"], "chat": self.sid, "member": child_id})
        errors = []
        command = persistence.pane_command(pane, tree.path(), parent, errors)
        self.assertEqual(errors, [])
        self.assertEqual(command[-2:], ["--session", child_id])
        self.assertIn("CONTEXT_ID=" + self.parent["id"], command)

    def test_native_deletion_is_portable_and_does_not_resurrect(self):
        library.sync_all()
        with closing(sqlite3.connect(library.database_path())) as db, db:
            db.execute("DELETE FROM session WHERE id=?", (self.sid,))
        library.sync_all(hydrate=True)
        archive, current = self.index()
        index = json.loads((archive.view(current) / "index.json").read_bytes())
        self.assertTrue(index["chats"][self.sid]["deleted"])
        library.sync_all(hydrate=True)
        self.assertNotIn(self.sid, library.native_rows(library.database_path()))

    def test_restore_into_empty_native_index(self):
        library.sync_all()
        self.environment("empty-device")
        self.assertFalse(library.database_path().exists())
        reference = {"owner": self.child["id"], "chat": self.sid, "member": self.sid}
        sid, directory = library.restore_reference(reference)
        self.assertTrue(library.database_path().is_file())
        self.assertEqual(library.chats._export(sid, directory)["info"]["metadata"]["desktop_context"]["session"], self.sid)
