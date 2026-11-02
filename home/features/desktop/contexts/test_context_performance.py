"""Flow regressions: forbid unrelated IO, not just assert mocked call counts."""

from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import contextctl as ctl
import context_chat_library as library
import context_notes
import organization
import persistence as p


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory(dir="/tmp/opencode"))
        self.base = Path(self.temp)
        self.enterContext(patch.dict(os.environ, {
            "CONTEXT_ROOT": str(self.base / "contexts"), "XDG_STATE_HOME": str(self.base / "state"),
            "XDG_RUNTIME_DIR": str(self.base), "HYPRLAND_INSTANCE_SIGNATURE": "flow-test",
            "CONTEXT_ID": "", "CONTEXT_DIRECTORY": "", "TMUX": "",
        }))
        self.first = ctl.create("First")
        self.other = ctl.create("Other", "/mnt/unrelated-offline")
        self.context = ctl.selected_context(self.first["id"])
        ctl.save_state({"mappings": {self.first["id"]: "runtime"}, "last_active": None})
        self.runtime()

    def runtime(self, count=1):
        ctl.atomic_json(ctl.runtime_path("hyprland-sessions"), {
            "sessions": [{"id": "runtime", "name": "First", "window_count": count}], "active": "runtime"})

    def test_selected_launch_close_and_card_survive_unrelated_corruption_without_walks(self):
        (ctl.root() / "Other/.context/context.json").write_text("incomplete sync")
        note = Path(self.context["path"]) / ".context/notes/Task.md"
        note.write_text("Task body\n")
        events = []
        with ExitStack() as stack:
            stack.enter_context(patch.object(ctl, "scan", side_effect=AssertionError("all-context walk")))
            stack.enter_context(patch.object(ctl, "publish", side_effect=AssertionError("full publication")))
            stack.enter_context(patch.object(ctl, "clients", return_value=[]))
            stack.enter_context(patch.object(ctl, "spawn"))
            stack.enter_context(patch.object(ctl, "evaluate", side_effect=lambda *_: events.append("dispatch")))
            stack.enter_context(patch.object(ctl, "close_kitty_windows", return_value=[]))
            stack.enter_context(patch.object(p, "checkpoint", side_effect=lambda *_: events.append("save")))
            ctl.open_context(self.first["id"])
            ctl.terminal("runtime")
            context_notes.resolve(self.first["id"]).open({"path": "Task.md"})
            ctl.close_context("runtime")
        self.assertEqual(events[-2:], ["save", "dispatch"])

    def test_stale_index_never_claims_replaced_or_moved_owner(self):
        directory = Path(self.context["path"])
        moved = directory.with_name("Moved")
        directory.rename(moved)
        metadata = ctl.read_json(moved / ".context/context.json")
        metadata["name"] = "Moved"
        ctl.atomic_json(moved / ".context/context.json", metadata)
        with patch.object(ctl, "scan", side_effect=AssertionError("foreground reconciliation")):
            with self.assertRaises(ctl.ContextError):
                ctl.selected_context(self.first["id"])
        ctl.scan(check_working_directories=False)
        self.assertEqual(ctl.selected_context(self.first["id"])["path"], str(moved))
        metadata["id"] = self.other["id"]
        ctl.atomic_json(moved / ".context/context.json", metadata)
        with self.assertRaisesRegex(ctl.ContextError, "ownership"):
            ctl.selected_context(self.first["id"])

    def test_selected_offline_probe_is_bounded_and_outside_mutation_lock(self):
        release = threading.Event()
        original = Path.is_dir

        def probe(path):
            if str(path) == "/mnt/selected-offline":
                with ctl.mutation_lock():
                    release.wait(3)
                return False
            return original(path)

        item = dict(self.context, working_directory_path="/mnt/selected-offline")
        try:
            with patch.object(Path, "is_dir", probe):
                start = time.monotonic()
                resolved = ctl.check_directory(item)
                self.assertLess(time.monotonic() - start, .5)
                self.assertEqual(resolved["cwd"], item["path"])
        finally:
            release.set()

    def test_watcher_runtime_updates_do_not_rescan_or_refresh_unchanged_scopes(self):
        original_scan = ctl.scan
        scans = []

        def scan(**kwargs):
            # Prove discovery is outside the foreground lock.
            with (ctl.state_root() / "contextctl.lock").open("a") as stream:
                ctl.fcntl.flock(stream, ctl.fcntl.LOCK_EX | ctl.fcntl.LOCK_NB)
            self.assertEqual(kwargs, {"check_working_directories": False})
            scans.append(True)
            return original_scan(**kwargs)

        ticks = 0

        def tick(_):
            nonlocal ticks
            ticks += 1
            if ticks == 1:
                self.runtime(2)
            else:
                raise KeyboardInterrupt

        with patch.object(ctl, "scan", side_effect=scan), patch.object(ctl, "reconcile_notes"), \
                patch.object(library, "refresh_scopes", return_value=True) as refresh, \
                patch.object(ctl.time, "sleep", side_effect=tick):
            with self.assertRaises(KeyboardInterrupt):
                ctl.watch()
        self.assertEqual(len(scans), 1)
        refresh.assert_called_once()
        self.assertEqual(ctl.read_json(ctl.runtime_path("desktop-contexts"))["contexts"][0]["window_count"], 2)

    def test_organization_never_probes_any_work_root(self):
        original = Path.is_dir

        def probe(path):
            if str(path).startswith("/mnt/"):
                raise AssertionError("unrelated availability probe")
            return original(path)

        with patch.object(Path, "is_dir", probe):
            organization.change([self.first["id"]], parent=self.other["id"])
            organization.undo()
            ctl.publish()

    def test_reference_reads_selected_session_and_owner_only(self):
        database = self.base / "native.db"
        row = {"owner": self.first["id"], "chat": "ses_family", "member": "ses_member"}
        with patch.object(library, "native_rows", return_value={"ses_selected": row}) as rows, \
                patch.object(library, "sync_context") as sync, \
                patch.object(ctl, "scan", side_effect=AssertionError("all-context walk")):
            result = library.reference({"database": str(database), "session_id": "ses_selected"})
        rows.assert_called_once_with(database, session="ses_selected")
        sync.assert_called_once_with(self.context, database, only_chat="ses_family")
        self.assertEqual(result["owner"], self.first["id"])

    def test_targeted_scopes_leave_unrelated_ledgers_and_scope_files_untouched(self):
        database = self.base / "native.db"
        database.touch()
        other_scope = library.scope_path(ctl.selected_context(self.other["id"]), database)
        ctl.atomic_json(other_scope, {"sentinel": True})
        original = ctl.read_json

        def read(path, *args):
            if path.name == self.other["id"] + ".json" and "databases" in path.parts:
                raise AssertionError("read unrelated ledger")
            return original(path, *args)

        with patch.object(library, "sync_context"), patch.object(library, "native_rows", return_value={}) as rows, \
                patch.object(ctl, "read_json", side_effect=read):
            library.sync_all(ctl.known_contexts(), database, only={self.first["id"]})
        self.assertTrue(all(call.args[1] == self.first["id"] for call in rows.call_args_list))
        self.assertEqual(ctl.read_json(other_scope), {"sentinel": True})

    def test_dirty_maintenance_skips_unchanged_and_saves_changed_closed_owner(self):
        database = self.base / "native.db"
        database.touch()
        rows = {"ses_one": {"id": "ses_one", "owner": self.other["id"], "updated": 1, "title": "closed"}}
        with patch.object(library, "known_databases", return_value=[database]), \
                patch.object(library, "native_rows", return_value=rows), \
                patch.object(library, "publish_scopes"), patch.object(library, "sync_context") as sync:
            contexts = ctl.known_contexts()
            library.sync_dirty(contexts)
            self.assertEqual(sync.call_count, 2)
            sync.reset_mock()
            library.sync_dirty(contexts)
            sync.assert_not_called()
            rows["ses_one"]["updated"] = 2
            library.sync_dirty(contexts)
            self.assertEqual(sync.call_args.args[0]["id"], self.other["id"])

    def test_readiness_waits_are_independent_and_failures_stay_pending(self):
        slow_started, fast_finished, release = threading.Event(), threading.Event(), threading.Event()
        tm = Mock()
        pending = [(sid, tm, sid, {"id": sid}, [], None, None) for sid in ("slow", "fast")]
        mapping = {sid: {"complete": True} for sid in ("slow", "fast")}
        errors = []

        def acknowledge(_tm, target, *_):
            if target == "slow":
                slow_started.set()
                release.wait(3)
                raise p.CheckpointError("failed slow recovery")
            fast_finished.set()

        with patch.object(p, "acknowledge_program", side_effect=acknowledge):
            thread = threading.Thread(target=p.finish_acknowledgements, args=(pending, mapping, errors))
            thread.start()
            try:
                self.assertTrue(slow_started.wait(1))
                self.assertTrue(fast_finished.wait(1), "slow readiness serialized independent panes")
            finally:
                release.set()
                thread.join(4)
        self.assertFalse(mapping["slow"]["complete"])
        self.assertTrue(mapping["fast"]["complete"])
        tm.call.assert_called_once_with("set-option", "-pu", "-t", "fast", "@persistence-recovery-pending")

    def test_dirty_maintenance_publishes_independent_owner_while_one_is_slow(self):
        database = self.base / "native.db"
        database.touch()
        entered, independent, release = threading.Event(), threading.Event(), threading.Event()

        def sync(context, *_args, **_kwargs):
            if context["id"] == self.first["id"]:
                entered.set()
                release.wait(3)
            else:
                independent.set()

        with patch.object(library, "known_databases", return_value=[database]), \
                patch.object(library, "native_rows", return_value={}), \
                patch.object(library, "publish_scopes"), patch.object(library, "sync_context", side_effect=sync):
            thread = threading.Thread(target=library.sync_dirty, args=(ctl.known_contexts(),))
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(independent.wait(1))
            finally:
                release.set()
                thread.join(4)

    def test_unchanged_owner_gets_bounded_dependency_reconciliation(self):
        database = self.base / "native.db"
        database.touch()
        with patch.object(library, "known_databases", return_value=[database]), \
                patch.object(library, "native_rows", return_value={}), \
                patch.object(library, "publish_scopes"), patch.object(library, "sync_context") as sync:
            contexts = ctl.known_contexts()
            library.sync_dirty(contexts)
            sync.reset_mock()
            with patch.object(library.time, "time", return_value=time.time() + 61):
                library.sync_dirty(contexts)
            self.assertEqual(sync.call_count, 1)

    def test_runtime_only_close_selects_attachments_before_pane_inventory(self):
        ctl.atomic_json(ctl.runtime_path("hyprland-sessions"), {
            "sessions": [{"id": "runtime", "name": "Temporary", "windows": ["0xown"]}], "active": "runtime"})
        tm = Mock()
        tm.rows.side_effect = [
            [{"session_id": "$1", "client_pid": "10"}, {"session_id": "$2", "client_pid": "20"}], [],
        ]
        with patch.object(ctl, "clients", return_value=[{"address": "0xown", "pid": 100}, {"address": "0xother", "pid": 200}]), \
                patch.object(p, "descendant", side_effect=lambda pid, ancestor: (pid, ancestor) == (10, 100)), \
                patch.object(ctl, "scan", side_effect=AssertionError("context tree discovery")):
            self.assertEqual(p.runtime_targets(tm, "runtime"), ["$1"])
        self.assertEqual([call.args[0] for call in tm.rows.call_args_list], ["list-clients", "list-sessions"])


if __name__ == "__main__":
    unittest.main()
