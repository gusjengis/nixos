"""Ownership/scoping contracts plus opt-in native portable-library round trips."""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
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
        os.environ.pop("CONTEXT_ID", None)
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

    def test_unchanged_library_reads_index_without_loading_conversation_history(self):
        context = ctl.find_context(self.child["id"])
        database = self.base / "fixture.db"
        database.touch()
        archive = library.storage(context)
        origin = "ses_lazyhistory"
        fingerprint = "unchanged"
        tree = library.store.Tree({
            "index.json": library.store.canonical({"version": 1, "chats": {
                origin: {"fingerprint": fingerprint, "deleted": False}}}),
            "conversations/" + origin + "/history.json": b"historical conversation" * 1000,
        })
        archive.publish(tree, {"device": "source", "context_id": context["id"], "warnings": []}, None)
        library.write_json(library.ledger_path(context, database), {"chats": {origin: {
            "local_id": origin, "source": fingerprint, "native": fingerprint}}})
        rows = {origin: {"id": origin, "owner": context["id"], "parent": None,
                         "chat": origin, "directory": str(self.work), "updated": 1}}
        original = library.store.Store.view
        accessed = []

        def index_only(storage, manifest):
            view = original(storage, manifest)
            loader = view.tree.loader

            def read(name):
                accessed.append(name)
                if name != "index.json":
                    raise AssertionError("Unchanged history must stay lazy")
                return loader(name)
            view.tree.loader = read
            return view

        with patch.object(library, "native_rows", return_value=rows), \
                patch.object(library.chats, "fingerprint", return_value=fingerprint), \
                patch.object(library.store.Store, "view", index_only), \
                patch.object(library.store.Store, "validate", side_effect=AssertionError("eager validation")), \
                patch.object(library.store.Store, "publish", side_effect=AssertionError("no-op publication")):
            library.sync_context(context, database)
        self.assertEqual(accessed, ["index.json"])

    def test_local_publication_before_ledger_commit_never_publishes_outdated(self):
        context = ctl.find_context(self.child["id"])
        database = self.base / "fixture.db"
        database.touch()
        origin = "ses_localcheckpoint"
        rows = {origin: {"id": origin, "owner": context["id"], "chat": origin,
                         "member": origin, "parent": None}}
        old = {"local_id": origin, "source": "r1", "native": "r1"}
        new = {"local_id": origin, "source": "r2", "native": "r2"}
        ledger = library.ledger_path(context, database)
        library.write_json(ledger, {"chats": {origin: old}})
        entry = {"fingerprint": "r2", "source_device": library.socket.gethostname()}
        library.recovery.begin_publication(ledger.with_suffix(".publication.json"), "head1",
                                           {"chats": {origin: new}}, {origin: entry})
        path = library.state_file(context, database)
        head = self.base / "head.json"
        head.write_text("head2")
        token = library.chat_state.head_token(head)
        library.chat_state.publish(path, context["id"], origin, selected_root=origin,
                                   members={origin: origin}, base_revision="r1", known_revision="r1",
                                   freshness="current_as_known", availability="local")
        original = library.chat_state._write
        published = []
        def capture(path, snapshot):
            published.append(snapshot["conversations"][library.chat_state.key(context["id"], origin)].copy())
            return original(path, snapshot)
        with patch.object(library.chat_state, "_write", side_effect=capture):
            state = library.observe_conversation(context, database, origin, entry, {}, str(head), token, rows)
        self.assertEqual(state["base_revision"], "r2")
        self.assertEqual(state["freshness"], "current_as_known")
        self.assertEqual(len(published), 1)
        self.assertTrue(all(row["known_revision"] == row["base_revision"] for row in published))
        # Same hostname is not an exemption: only our durable publication matches.
        remote = dict(entry, fingerprint="r3")
        state = library.observe_conversation(context, database, origin, remote, {}, str(head), token, rows)
        self.assertEqual(state["freshness"], "outdated")

    def test_checkpoint_batch_reuses_successful_sync_but_not_failures_or_future_saves(self):
        database = self.base / "fixture.db"
        database.touch()
        contexts = [ctl.find_context(self.child["id"])]
        with patch.object(library, "sync_context") as sync, patch.object(library, "publish_scopes"):
            with library.sync_batch():
                library.sync_all(contexts, database)
                library.sync_all(contexts, database)
            self.assertEqual(sync.call_count, 1)
            with library.sync_batch():
                library.sync_all(contexts, database)
            self.assertEqual(sync.call_count, 2)
            with library.sync_batch():
                sync.side_effect = library.chats.ChatChangedDuringCheckpoint("busy")
                errors = []
                library.sync_all(contexts, database, errors=errors)
                sync.side_effect = None
                library.sync_all(contexts, database)
            self.assertEqual(len(errors), 1)
            self.assertEqual(sync.call_count, 4)

    def test_periodic_checkpoint_does_not_import_archived_history(self):
        with patch.object(ctl, "scan", return_value=[]), \
                patch.object(persistence, "sockets", return_value=[]), \
                patch.object(library, "sync_dirty") as sync:
            persistence.checkpoint(reason="periodic")
        self.assertEqual(sync.call_args.args[0], [])

    def test_launch_never_probes_work_roots_or_waits_for_library(self):
        context = ctl.find_context(self.child["id"])
        original_resolve, original_is_dir = Path.resolve, Path.is_dir
        roots = [self.work, self.base / "offline"]

        def guard(method):
            def checked(path, *args, **kwargs):
                if any(path == root or path.is_relative_to(root) for root in roots):
                    raise AssertionError("Launch accessed a working directory: " + str(path))
                return method(path, *args, **kwargs)
            return checked

        with patch.dict(os.environ, {"CONTEXT_DIRECTORY": context["path"]}), \
                patch.object(Path, "resolve", guard(original_resolve)), \
                patch.object(Path, "is_dir", guard(original_is_dir)), \
                patch.object(library, "sync_all", side_effect=AssertionError("Launch synchronized history")), \
                patch.object(library.os, "execv") as execute, library.library_lock():
            os.environ.pop("TMUX", None)
            os.environ.pop("OPENCODE_CONTEXT_HELPER", None)
            library.launch("/native/opencode", [])
            execute.assert_called_once_with("/native/opencode", ["/native/opencode"])
            self.assertEqual(os.environ["CONTEXT_ID"], context["id"])
            scope = ctl.read_json(Path(os.environ["OPENCODE_CONTEXT_SCOPE_FILE"]))
            self.assertEqual(scope["ids"], [context["id"]])

    def test_cli_helpers_do_not_scan_or_synchronize(self):
        for arguments in (["db", "path"], ["--version"], ["export", "ses_fixture"]):
            with patch.object(ctl, "scan", side_effect=AssertionError("Helper scanned contexts")), \
                    patch.object(library.os, "execv", side_effect=SystemExit) as execute:
                with self.assertRaises(SystemExit):
                    library.launch("/native/opencode", arguments)
                execute.assert_called_once_with("/native/opencode", ["/native/opencode", *arguments])

    def test_prepare_discovers_without_hydration_or_workroot_probes(self):
        child = ctl.find_context(self.child["id"])
        original = Path.is_dir

        def checked(path):
            if path == self.base / "offline" or path == self.work:
                raise AssertionError("Discovery probed a working root")
            return original(path)

        with patch.dict(os.environ, {"CONTEXT_ID": child["id"]}), \
                patch.object(Path, "is_dir", checked), \
                patch.object(library, "sync_all", side_effect=AssertionError("Discovery synchronized")), \
                patch.object(library.chats, "fingerprint", side_effect=AssertionError("Discovery fingerprinted")):
            result = library.prepare()
        self.assertTrue(all(row["owner"] == child["id"] for row in result["conversations"]))

    def test_portable_summaries_only_read_index_and_scope_failures(self):
        context = ctl.find_context(self.child["id"])
        archive = library.storage(context)
        origin = "ses_portableonly"
        tree = library.store.Tree({"index.json": library.store.canonical({"version": 1, "chats": {
            origin: {"fingerprint": "rev", "deleted": False, "title": "Portable title", "updated": 100}}}),
            "conversations/" + origin + "/history.json": b"not needed"})
        archive.publish(tree, {"context_id": context["id"], "device": "other"}, None)
        sibling_archive = library.storage(ctl.find_context(self.sibling["id"]))
        sibling_archive.directory.mkdir(parents=True)
        (sibling_archive.directory / "current.json").write_text("incomplete incoming manifest")
        original = library.store.Store.view
        reads = []
        def index_only(archive, current):
            view = original(archive, current)
            loader = view.tree.loader
            def read(name):
                reads.append(name)
                self.assertEqual(name, "index.json")
                return loader(name)
            view.tree.loader = read
            return view
        with patch.dict(os.environ, {"CONTEXT_ID": self.parent["id"]}), \
                patch.object(library.store.Store, "view", index_only), \
                patch.object(library.chats, "restore", side_effect=AssertionError("Summary imported")):
            result = library.list_summaries()
        self.assertEqual(reads, ["index.json"])
        self.assertEqual(result["conversations"][0]["title"], "Portable title")
        self.assertEqual(result["conversations"][0]["state"]["availability"], "portable_only")
        self.assertEqual(result["errors"][0]["owner"], self.sibling["id"])
        with patch.dict(os.environ, {"CONTEXT_ID": self.parent["id"]}), \
                patch.object(library.store.Store, "view", side_effect=AssertionError("Warm summary loaded artifacts")), \
                patch.object(library.chat_state, "publish", side_effect=AssertionError("Warm summary rewrote state")):
            library.list_summaries()
        (archive.directory / "conflicts").mkdir()
        (archive.directory / "conflicts/incoming.json").write_text("{}")
        with patch.dict(os.environ, {"CONTEXT_ID": self.parent["id"]}):
            conflicted = library.list_summaries()
        portable = next(row for row in conflicted["conversations"] if row["chat"] == origin)
        self.assertEqual(portable["state"]["freshness"], "conflict")
        self.assertEqual(portable["state"]["availability"], "waiting_data")

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

    def test_local_checkpoint_discovered_before_ledger_commit_stays_current(self):
        context = self.child_context()
        database = library.database_path()
        with patch.dict(os.environ, {"CONTEXT_ID": context["id"]}):
            library.sync_context(context, database)
            before = library.check_conversation(context["id"], self.sid)
            self.edit_title(self.sid, "Locally checkpointed update")
            publish = library.store.Store.publish
            observed = []

            def discover_after_head(archive, *args, **kwargs):
                result = publish(archive, *args, **kwargs)
                # Exact window: head visible, durable intent present, ledger old.
                observed.append(library.check_conversation(context["id"], self.sid))
                return result

            with patch.object(library.store.Store, "publish", discover_after_head):
                library.sync_context(context, database)
            after = library.check_conversation(context["id"], self.sid)
        self.assertEqual(len(observed), 1)
        self.assertNotEqual(before["known_revision"], after["known_revision"])
        for state in [*observed, after]:
            self.assertEqual(state["freshness"], "current_as_known")
            self.assertEqual(state["known_revision"], state["base_revision"])
            self.assertEqual(state["selected_root"], self.sid)

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

    def test_prepare_lists_local_history_without_publishing_or_importing(self):
        with patch.dict(os.environ, {"CONTEXT_ID": self.child["id"]}):
            result = library.prepare()
        self.assertIsNone(self.index()[1])
        self.assertEqual(result["conversations"][0]["chat"], self.sid)

    def test_selected_restore_ignores_missing_unselected_artifacts_and_warm_path_is_cheap(self):
        second = {"info": dict(self.fixture["info"], id="ses_unselected", title="Unselected"), "messages": []}
        second["info"]["metadata"] = {"desktop_context": {
            "id": self.child["id"], "chat": "ses_unselected", "session": "ses_unselected"}}
        self.import_chat(second)
        library.sync_all()
        archive, current = self.index()
        self.assertEqual(json.loads((archive.view(current) / "index.json").read_bytes())["chats"][self.sid]["title"], self.fixture["info"]["title"])
        # Missing sibling objects must never be validated/materialized for selected import.
        selected_chunks = {key for name, info in current["artifacts"].items()
                           if not name.startswith("conversations/ses_unselected/") for key in info["chunks"]}
        for name, info in current["artifacts"].items():
            if name.startswith("conversations/ses_unselected/"):
                for key in set(info["chunks"]) - selected_chunks:
                    archive.object(key).unlink(missing_ok=True)
        self.environment("selected-destination")
        reference = {"owner": self.child["id"], "chat": self.sid, "member": self.sid}
        imported = []
        original_restore = library.chats.restore
        def restore(bundle, *args, **kwargs):
            imported.append(Path(bundle).name)
            return original_restore(bundle, *args, **kwargs)
        with patch.object(library.chats, "restore", side_effect=restore), \
                library.worker.scoped_lock(self.child["id"]):
            sid, directory = library.restore_reference(reference)
        self.assertEqual(imported, [self.sid])
        self.assertEqual({row["chat"] for row in library.native_rows(library.database_path()).values()}, {self.sid})
        with patch.object(library.chats, "fingerprint", side_effect=AssertionError("Warm path fingerprinted transcript")), \
                patch.object(library.chats, "restore", side_effect=AssertionError("Warm path imported")), \
                patch.object(library, "sync_all", side_effect=AssertionError("Warm path synchronized library")), \
                patch.object(library, "library_lock", side_effect=AssertionError("Warm path took global lock")):
            state = library.check_conversation(self.child["id"], self.sid, sid)
            result = library.ensure_conversation(self.child["id"], self.sid, self.sid)
        self.assertEqual(state["freshness"], "current_as_known")
        self.assertEqual(result["session_id"], sid)
        self.assertEqual(result["directory"], directory)
        response = subprocess.run([sys.executable, "-B", library.__file__, "ensure", "--owner", self.child["id"],
                                   "--chat", self.sid, "--member", self.sid,
                                   "--expected-revision", state["known_revision"]],
                                  env=dict(os.environ, CONTEXT_ID=self.child["id"]), text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(response.stdout)["session_id"], sid)

    def test_publication_crash_recovers_matching_ledger_without_reexport(self):
        context = self.child_context()
        with patch.object(library.recovery, "finish_publication", side_effect=RuntimeError("simulated crash after archive commit")):
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                library.sync_context(context, library.database_path(), only_chat=self.sid)
        current = self.index()[1]
        self.assertIsNotNone(current)
        with patch.object(library.chats, "capture", side_effect=AssertionError("Recovery reexported verified history")):
            library.sync_context(context, library.database_path(), only_chat=self.sid)
        self.assertEqual(self.index()[1]["id"], current["id"])
        ledger = ctl.read_json(library.ledger_path(context, library.database_path()))
        self.assertEqual(ledger["chats"][self.sid]["local_id"], self.sid)
        self.assertFalse(library.ledger_path(context, library.database_path()).with_suffix(".publication.json").exists())

    def test_missing_selected_workdir_never_acknowledges_import(self):
        library.sync_all()
        self.environment("missing-workdir-device")
        ctl.set_working_directory(self.child["id"], str(self.base / "unavailable-work"))
        with patch.object(library.chats, "restore", side_effect=AssertionError("Missing root imported")):
            with self.assertRaisesRegex(ValueError, "working directory is unavailable"):
                library.ensure_conversation(self.child["id"], self.sid)
        context = ctl.find_context(self.child["id"])
        state = library.chat_state.get(library.state_file(context, library.database_path()), self.child["id"], self.sid)
        self.assertEqual(state["availability"], "missing_workdir")
        self.assertIsNone(state["selected_root"])

    def test_selected_completion_cannot_overwrite_newer_authoritative_generation(self):
        library.sync_all()
        self.environment("generation-race-device")
        publish = library.chat_state.publish
        def race(path, owner, chat, **fields):
            if fields.get("expected_generation") is not None and fields.get("freshness") == "current_as_known":
                publish(path, owner, chat, known_revision="new-arrival", freshness="outdated", operation={"phase": "idle"})
            return publish(path, owner, chat, **fields)
        with patch.object(library.chat_state, "publish", side_effect=race):
            with self.assertRaises(library.chat_state.StateChanged):
                library.ensure_conversation(self.child["id"], self.sid)
        context = self.child_context()
        state = library.chat_state.get(library.state_file(context, library.database_path()), self.child["id"], self.sid)
        self.assertEqual(state["known_revision"], "new-arrival")
        self.assertEqual(state["freshness"], "outdated")
        self.assertIsNone(state["selected_root"])
