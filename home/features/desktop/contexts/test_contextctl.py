import contextlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import socket
import tempfile
import time
import unittest
from unittest.mock import patch, Mock

import contextctl as ctl

POPEN = subprocess.Popen


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.env = patch.dict(os.environ, {
            "HOME": str(self.base / "home"), "CONTEXT_ROOT": str(self.base / "sessions"),
            "XDG_STATE_HOME": str(self.base / "state"), "XDG_RUNTIME_DIR": str(self.base),
            "HYPRLAND_INSTANCE_SIGNATURE": "test-signature",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.run = patch.object(ctl.subprocess, "run", return_value=Mock(returncode=0, stdout="[]", stderr="")).start()
        self.spawn = patch.object(ctl.subprocess, "Popen").start()
        self.addCleanup(patch.stopall)
        self.runtime([])

    def runtime(self, sessions, active=None):
        ctl.atomic_json(ctl.runtime_path("hyprland-sessions"), {"sessions": sessions, "active": active})

    def mapped(self, name="Projects/Alpha", runtime_id="s2"):
        item = ctl.create(name)
        ctl.save_state({"mappings": {item["id"]: runtime_id}, "last_active": None})
        self.runtime([{"id": runtime_id, "name": name, "window_count": 3}], runtime_id)
        return item

    def test_create_hierarchy(self):
        data = ctl.create("Projects/Alpha")
        directory = ctl.root() / "Projects/Alpha"
        self.assertEqual(data["name"], "Alpha")
        self.assertEqual(data["working_directory"], ".")
        self.assertEqual(ctl.read_json(directory / ".context/context.json"), data)
        self.assertTrue((directory / ".context/notes/.obsidian/app.json").exists())
        self.assertEqual(ctl.scan()[0]["name"], "Projects/Alpha")
        self.run.assert_not_called()
        self.spawn.assert_not_called()

    def test_invalid_names(self):
        for name in ("", "/absolute", "a/../b", ".hidden", "a/.context", "a//b", "a/", "a\nb", " a"):
            with self.subTest(name=name), self.assertRaises(ctl.ContextError):
                ctl.create(name)

    def test_work_is_an_ordinary_context_directory(self):
        ctl.create("work/Free")
        self.assertEqual(ctl.scan()[0]["name"], "work/Free")

    def test_registered_checkouts_are_not_context_trees(self):
        ctl.create("Parent")
        directory = ctl.root() / "Parent"
        data = ctl.read_json(directory / ".context/context.json")
        data["repositories"] = [{"path": "checkout"}]
        ctl.atomic_json(directory / ".context/context.json", data)
        (directory / "checkout/nested/.context").mkdir(parents=True)
        self.assertEqual([item["name"] for item in ctl.scan()], ["Parent"])
        with self.assertRaisesRegex(ctl.ContextError, "registered Git checkout"):
            ctl.create("Parent/checkout/Nested")

    def test_context_creation_through_checkout_symlink_rejected(self):
        ctl.create("Parent")
        directory = ctl.root() / "Parent"
        (directory / "checkout").mkdir()
        (directory / "shortcut").symlink_to(directory / "checkout", target_is_directory=True)
        data = ctl.read_json(directory / ".context/context.json")
        data["repositories"] = [{"path": "checkout"}]
        ctl.atomic_json(directory / ".context/context.json", data)
        with self.assertRaisesRegex(ctl.ContextError, "registered Git checkout"):
            ctl.create("Parent/shortcut/Nested")
        self.assertFalse((directory / "checkout/Nested").exists())

    def test_scanner_prunes_physical_checkout_behind_alias(self):
        ctl.create("Parent")
        directory = ctl.root() / "Parent"
        (directory / "physical/deep/.context").mkdir(parents=True)
        (directory / "alias").symlink_to(directory / "physical", target_is_directory=True)
        data = ctl.read_json(directory / ".context/context.json")
        data["repositories"] = [{"path": "alias"}]
        ctl.atomic_json(directory / ".context/context.json", data)
        self.assertEqual([item["name"] for item in ctl.scan()], ["Parent"])

    def test_symlink_escape(self):
        ctl.root().mkdir()
        (ctl.root() / "outside").symlink_to(self.base, target_is_directory=True)
        with self.assertRaisesRegex(ctl.ContextError, "escapes"):
            ctl.create("outside/Bad")

    def test_duplicate_ids_preserve_catalog(self):
        data = ctl.create("Alpha")
        other = ctl.create("Beta")
        ctl.publish()
        previous = ctl.runtime_path("desktop-contexts").read_bytes()
        other["id"] = data["id"]
        ctl.atomic_json(ctl.root() / "Beta/.context/context.json", other)
        with self.assertRaisesRegex(ctl.ContextError, "Duplicate"):
            ctl.publish()
        self.assertEqual(previous, ctl.runtime_path("desktop-contexts").read_bytes())
        with self.assertRaises(ctl.ContextError):
            ctl.create("Gamma")

    def test_incomplete_sync_preserves_catalog(self):
        ctl.create("Alpha")
        ctl.publish()
        previous = ctl.runtime_path("desktop-contexts").read_bytes()
        (ctl.root() / "Beta/.context").mkdir(parents=True)
        with self.assertRaises(ctl.ContextError):
            ctl.publish()
        self.assertEqual(previous, ctl.runtime_path("desktop-contexts").read_bytes())

    def test_open_reuses_mapping_without_notes(self):
        item = self.mapped()
        self.run.return_value.stdout = "ok"
        ctl.open_context(item["id"])
        self.assertEqual(self.run.call_count, 1)
        self.assertIn(".switch(", self.run.call_args.args[0][2])
        self.assertNotIn("show_special", self.run.call_args.args[0][2])

    def test_close_waits_for_checkpoint_before_any_window_close_request(self):
        import persistence
        item = self.mapped()
        order = []

        def backend(arguments, **kwargs):
            self.assertEqual(order, ["checkpoint"])
            self.assertIn("close_checkpointed", arguments[2])
            order.append("close")
            return Mock(returncode=0, stdout="ok", stderr="")

        self.run.side_effect = backend
        with patch.object(persistence, "checkpoint", side_effect=lambda *args: order.append("checkpoint")) as save:
            ctl.close_context("s2")
        save.assert_called_once_with("close", item["id"])
        self.assertEqual(order, ["checkpoint", "close"])
        self.assertEqual(ctl.read_json(persistence.local_root() / "lifecycle.json")[item["id"]], "closed")

    def test_close_checkpoint_failure_leaves_runtime_and_lifecycle_intact(self):
        import persistence
        item = self.mapped()
        persistence.set_lifecycle(ctl.find_context(item["id"]), "open")
        with patch.object(persistence, "checkpoint", side_effect=persistence.CheckpointError("incomplete chat")):
            with self.assertRaisesRegex(ctl.ContextError, "incomplete chat"):
                ctl.close_context("s2")
        self.run.assert_not_called()
        self.assertEqual(ctl.read_json(persistence.local_root() / "lifecycle.json")[item["id"]], "open")

    def test_kitty_close_targets_only_owned_unambiguous_instances(self):
        self.runtime([{"id": "s2", "name": "Target", "windows": ["0xa", "0xb", "0xc"]}])
        windows = [
            {"address": "0xa", "pid": 101, "class": "kitty"},
            {"address": "0xb", "pid": 102, "class": "context-terminal-example"},
            {"address": "0xc", "pid": 103, "class": "kitty"},
            {"address": "0xd", "pid": 103, "class": "kitty"},
            {"address": "0xe", "pid": 104, "class": "kitty"},
        ]
        for pid in (101, 102, 103, 104):
            endpoint = self.enterContext(socket.socket(socket.AF_UNIX))
            endpoint.bind(str(self.base / f"kitty-context-{pid}"))
        single = [{"tabs": [{"windows": [{"id": 7}, {"id": 8}]}]}]
        multiple = [*single, *single]
        self.run.side_effect = [Mock(returncode=0, stdout=json.dumps(single)),
                                Mock(returncode=0), Mock(returncode=0, stdout=json.dumps(multiple))]
        with patch.object(ctl, "clients", return_value=windows):
            self.assertEqual(ctl.close_kitty_windows("s2"), ["0xa"])
        self.assertEqual(self.run.call_count, 3)
        calls = [call.args[0] for call in self.run.call_args_list]
        self.assertEqual(calls[1][-3:], ["close-window", "--match", "id:7 or id:8"])
        self.assertTrue(all("kitty-context-103" not in str(call) and "kitty-context-104" not in str(call)
                            for call in calls))

    def test_kitty_close_failure_and_missing_socket_keep_normal_close(self):
        self.runtime([{"id": "s2", "name": "Target", "windows": ["0xa"]}])
        window = {"address": "0xa", "pid": 101, "class": "kitty"}
        with patch.object(ctl, "clients", return_value=[window]):
            self.assertEqual(ctl.close_kitty_windows("s2"), [])
            self.run.assert_not_called()
            endpoint = self.enterContext(socket.socket(socket.AF_UNIX))
            endpoint.bind(str(self.base / "kitty-context-101"))
            for result in (Mock(returncode=1), Mock(returncode=0, stdout="invalid"),
                           subprocess.TimeoutExpired("kitty", 3)):
                self.run.side_effect = [result]
                self.assertEqual(ctl.close_kitty_windows("s2"), [])

    def test_kitty_close_runs_after_checkpoint_and_passes_handled_windows(self):
        import persistence

        self.mapped()
        order = []
        with patch.object(persistence, "checkpoint", side_effect=lambda *_: order.append("save")), \
                patch.object(ctl, "close_kitty_windows", side_effect=lambda _: order.append("kitty") or ["0xa"]), \
                patch.object(ctl, "evaluate", side_effect=lambda code: order.append(code)):
            ctl.close_context("s2")
        self.assertEqual(order[:2], ["save", "kitty"])
        self.assertIn("close_checkpointed", order[2])
        self.assertIn("[" + ctl.lua_string("0xa") + "]=true", order[2])

    def test_slow_close_does_not_block_other_context_commands(self):
        import persistence
        item = self.mapped()
        other = ctl.create("Other")
        ctl.save_state({"mappings": {item["id"]: "s2", other["id"]: "s3"}, "last_active": None})
        self.runtime([{"id": "s2", "name": item["name"]}, {"id": "s3", "name": "Other"}], "s3")
        processes = multiprocessing.get_context("fork")
        entered, release = processes.Event(), processes.Event()
        result, sender = processes.Pipe(duplex=False)

        def checkpoint(*_args):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Test checkpoint was not released")

        def closing():
            with patch.object(persistence, "checkpoint", side_effect=checkpoint), patch.object(ctl, "evaluate"), \
                    contextlib.redirect_stdout(io.StringIO()):
                ctl.main(["close", "--runtime", "s2"])

        def unrelated():
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(ctl, "evaluate"):
                sender.send([ctl.main(args) for args in (["list"], ["terminal", "--runtime", "s3"],
                                                        ["files", "--runtime", "s3"], ["notes", "--runtime", "s3"],
                                                        ["open", other["id"]], ["close", "--runtime", "s2"])])

        close = processes.Process(target=closing)
        probe = processes.Process(target=unrelated)
        close.start()
        try:
            self.assertTrue(entered.wait(3), "close never reached checkpoint")
            probe.start()
            self.assertTrue(result.poll(2), "slow checkpoint holds global context lock; unrelated launches are blocked")
            self.assertEqual(result.recv(), [0, 0, 0, 0, 0, 1], "duplicate close must fail promptly without another checkpoint")
        finally:
            release.set()
            close.join(5)
            if probe.pid:
                probe.join(5)
            for process in (close, probe):
                if process.pid and process.is_alive():
                    process.terminate()
                    process.join()
            result.close()
            sender.close()
        self.assertEqual(close.exitcode, 0)
        self.assertEqual(probe.exitcode, 0)

    def test_close_does_not_target_runtime_that_disappeared_during_save(self):
        import persistence
        self.mapped()
        with patch.object(persistence, "checkpoint", side_effect=lambda *_args: self.runtime([])), \
                self.assertRaisesRegex(ctl.ContextError, "has closed"):
            ctl.close_context("s2")
        self.run.assert_not_called()

    def test_slow_restore_leaves_other_context_commands_available(self):
        import persistence
        other = self.mapped("Other", "s3")
        opening = ctl.create("Opening")
        processes = multiprocessing.get_context("fork")
        entered, release = processes.Event(), processes.Event()
        result, sender = processes.Pipe(duplex=False)
        saved = self.base / "checkpoint"
        saved.mkdir()
        ctl.atomic_json(saved / "tmux.json", [{"id": "saved-session"}])
        real_restore = persistence.restore

        def adapter(*_args):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("Test restore was not released")
            return {}

        def evaluate(statement):
            if ".create(" in statement:
                self.runtime([{"id": "s3", "name": "Other"}, {"id": "s4", "name": "Opening"}], "s4")

        def restoring():
            with patch.object(ctl, "evaluate", side_effect=evaluate), \
                    patch.object(persistence, "latest", return_value=(saved, {"warnings": []})), \
                    patch.object(persistence, "validate"), patch.object(persistence, "restore_tmux", side_effect=adapter), \
                    patch.object(persistence, "restore", side_effect=lambda context, runtime: real_restore(
                        context, runtime, tm=persistence.Tmux(self.base / "unused.sock"), windows=False)), \
                    contextlib.redirect_stdout(io.StringIO()):
                ctl.main(["open", opening["id"]])

        def unrelated():
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(ctl, "evaluate"):
                sender.send([ctl.main(args) for args in (["list"], ["terminal", "--runtime", "s3"],
                    ["files", "--runtime", "s3"], ["notes", "--runtime", "s3"], ["open", other["id"]],
                    ["open", opening["id"]], ["close", "--runtime", "s4"])])

        restore = processes.Process(target=restoring)
        probe = processes.Process(target=unrelated)
        restore.start()
        try:
            self.assertTrue(entered.wait(3), "restore never reached application startup")
            probe.start()
            self.assertTrue(result.poll(2), "restore blocks catalog, launchers or switching through global locks")
            self.assertEqual(result.recv(), [0, 0, 0, 0, 0, 0, 1])
        finally:
            release.set()
            restore.join(5)
            if probe.pid:
                probe.join(5)
            for process in (restore, probe):
                if process.pid and process.is_alive():
                    process.terminate()
                    process.join()
            result.close()
            sender.close()
        self.assertEqual(restore.exitcode, 0)
        self.assertEqual(probe.exitcode, 0)

    def test_background_open_returns_before_worker_and_reuses_mapping(self):
        item = ctl.create("Opening")
        started, release = self.base / "started", self.base / "release"
        worker = self.base / "worker.py"
        worker.write_text(
            "import sys,time\nfrom pathlib import Path\n"
            + "sys.path.insert(0," + repr(str(Path(ctl.__file__).parent)) + ")\n"
            + "import contextctl as ctl, persistence as p\n"
            + "def restore(*args):\n"
            + "    Path(" + repr(str(started)) + ").touch()\n"
            + "    deadline=time.monotonic()+10\n"
            + "    while not Path(" + repr(str(release)) + ").exists():\n"
            + "        if time.monotonic()>deadline: raise ctl.ContextError('worker deadline')\n"
            + "        time.sleep(.01)\n"
            + "p.restore=restore\nsys.exit(ctl.main(sys.argv[1:]))\n")
        children = []

        def launch(arguments):
            children.append(POPEN(arguments, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))

        def backend(arguments, **_kwargs):
            if ".create(" in arguments[2]:
                self.runtime([{"id": "s4", "name": "Opening"}], "s4")
            return Mock(returncode=0, stdout="ok", stderr="")

        self.run.side_effect = backend
        try:
            with patch.object(ctl, "__file__", str(worker)), patch.object(ctl, "spawn", side_effect=launch), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ctl.main(["open", item["id"], "--background"]), 0)
                deadline = time.monotonic() + 3
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(started.exists(), "detached worker did not start")
                self.assertIsNone(children[0].poll(), "open waited for application restoration")
                self.assertEqual(ctl.local_state()["mappings"][item["id"]], "s4")
                self.assertEqual(ctl.main(["open", item["id"], "--background"]), 0)
                self.assertEqual(len(children), 1, "reopening must not start duplicate reconstruction")
                self.assertEqual(ctl.main(["close", "--runtime", "s4"]), 1, "close must reject in-flight restoration")
        finally:
            release.touch()
            for child in children:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.terminate()
                    child.wait()
        self.assertEqual(children[0].returncode, 0)

    def test_detached_restore_rejects_stale_mapping_and_reports_failure(self):
        import persistence
        item = self.mapped()
        self.runtime([])
        with patch.object(persistence, "restore") as restore, patch.object(persistence, "notify") as notify, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ctl.main(["restore-runtime", item["id"], "s2"]), 1)
        restore.assert_not_called()
        self.assertIn("has closed", notify.call_args.args[0][0])

    def test_create_and_open_background_uses_same_restore_worker(self):
        import persistence

        def backend(arguments, **_kwargs):
            if ".create(" in arguments[2]:
                self.runtime([{"id": "s4", "name": "New"}], "s4")
            return Mock(returncode=0, stdout="ok", stderr="")

        self.run.side_effect = backend
        with patch.object(persistence, "restore") as restore, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ctl.main(["create", "New", "--open", "--background"]), 0)
        item = ctl.scan()[0]
        self.assertEqual(self.spawn.call_args.args[0][-3:], ["restore-runtime", item["id"], "s4"])
        self.assertEqual(ctl.local_state()["mappings"][item["id"]], "s4")
        restore.assert_not_called()

    def test_create_runtime_mapping_saved_before_notes(self):
        item = ctl.create('Projects/Quote " and \\ unicode é')

        def backend(arguments, **kwargs):
            statement = arguments[2]
            if ".create(" in statement:
                self.runtime([{"id": "s8", "name": 'Projects/Quote " and \\ unicode é'}], "s8")
            if "show_special" in statement:
                self.assertEqual(ctl.local_state()["mappings"][item["id"]], "s8")
            return Mock(returncode=0, stdout="ok", stderr="")

        self.run.side_effect = backend
        ctl.open_context(item["id"])
        self.assertEqual(self.run.call_count, 2)
        self.assertIn("show_special('notes')", self.run.call_args.args[0][2])
        self.assertNotIn("é", self.run.call_args_list[0].args[0][2])

    def test_stale_mapping_close_reopen(self):
        item = self.mapped()
        self.runtime([])
        self.assertIsNone(ctl.catalog()["contexts"][0]["runtime_id"])

        def backend(arguments, **kwargs):
            if ".create(" in arguments[2]:
                self.runtime([{"id": "s9", "name": "Projects/Alpha"}], "s9")
            return Mock(returncode=0, stdout="ok", stderr="")

        self.run.side_effect = backend
        ctl.open_context(item["id"])
        self.assertEqual(ctl.local_state()["mappings"][item["id"]], "s9")

    def test_unmapped_name_not_claimed(self):
        item = ctl.create("Alpha")
        self.runtime([{"id": "s2", "name": "Alpha"}])
        with self.assertRaisesRegex(ctl.ContextError, "refusing"):
            ctl.open_context(item["id"])
        self.run.assert_not_called()

    def test_working_directory_validation_and_fallback(self):
        for value in ("../outside", "work/../../bad", "", "bad\x00path", "bad\npath"):
            with self.subTest(value=value), self.assertRaises(ctl.ContextError):
                ctl.create("Invalid", value)
        item = ctl.create("Repo", "work/Repo")
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(ctl.find_context(item["id"])["cwd"], str(ctl.root() / "Repo"))
        self.assertIn("notebook remains available", errors.getvalue())
        with contextlib.redirect_stderr(io.StringIO()) as repeated:
            ctl.scan()
        self.assertEqual(repeated.getvalue(), "")
        directory = ctl.root() / "Repo/work"
        directory.mkdir()
        (directory / "Repo").mkdir()
        self.assertEqual(ctl.find_context(item["id"])["cwd"], str(directory / "Repo"))
        (directory / "Repo").rmdir()
        (directory / "Repo").symlink_to(self.base)
        with self.assertRaisesRegex(ctl.ContextError, "escapes"):
            ctl.scan()

    def test_external_working_directory_preserves_home_and_context_identity(self):
        first = self.mapped("First", "s1")
        second = self.mapped("Second", "s2")
        ctl.save_state({"mappings": {first["id"]: "s1", second["id"]: "s2"}, "last_active": None})
        self.runtime([{"id": "s1", "name": "First"}, {"id": "s2", "name": "Second"}], "s1")
        target = self.base / "external repo"
        target.mkdir()
        for item in (first, second):
            metadata = ctl.root() / item["name"] / ".context/context.json"
            before = ctl.read_json(metadata)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ctl.main(["set-working-directory", item["id"], str(target)]), 0)
            self.assertEqual(ctl.read_json(metadata), dict(before, working_directory=str(target)))
            resolved = ctl.find_context(item["id"])
            self.assertEqual(resolved["path"], str(metadata.parent.parent))
            self.assertEqual(resolved["cwd"], str(target))
            self.assertTrue((metadata.parent / "notes/Home.md").is_file())
            node = next(node for node in ctl.catalog()["nodes"] if node["id"] == item["id"])
            self.assertEqual(node["working_directory"], str(target))
            ctl.terminal("s1" if item == first else "s2")
            args = self.spawn.call_args.args[0]
            self.assertIn("context-" + item["id"], args)
            self.assertEqual(args[-4:], ["create-tmux-session", str(target),
                                        "context-" + item["id"], "--attach"])
        self.assertFalse((target / ".context").exists())

    def test_working_directory_edit_missing_target_and_reset(self):
        item = ctl.create("Job")
        home = ctl.root() / "Job"
        metadata = home / ".context/context.json"
        target = self.base / "unmounted drive/job"
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ctl.main(["set-working-directory", item["id"], str(target)]), 0)
            resolved = ctl.find_context(item["id"])
        self.assertEqual(resolved["cwd"], str(home))
        self.assertEqual(resolved["working_directory_path"], str(target))
        self.assertFalse(resolved["working_directory_available"])
        self.assertFalse(target.exists())
        target.mkdir(parents=True)
        self.assertEqual(ctl.find_context(item["id"])["cwd"], str(target))
        before = metadata.read_bytes()
        with self.assertRaises(ctl.ContextError):
            ctl.set_working_directory(item["id"], "../escape")
        self.assertEqual(metadata.read_bytes(), before)
        (home / "repo").mkdir()
        ctl.set_working_directory(item["id"], "repo")
        self.assertEqual(ctl.find_context(item["id"])["cwd"], str(home / "repo"))
        ctl.set_working_directory(item["id"], ".")
        self.assertEqual(ctl.find_context(item["id"])["cwd"], str(home))

    def test_unmanaged_notes_preserve_general_notebook_launcher(self):
        self.runtime([{"id": "s99", "name": "Runtime only"}], "s99")
        ctl.notes("s99")
        self.assertEqual(self.spawn.call_args.args[0], ["obsidian"])

    def test_notes_profile_preserved_and_home_not_overwritten(self):
        item = self.mapped()
        note = ctl.root() / "Projects/Alpha/.context/notes/Home.md"
        note.write_text("User notes\n")
        vault_config = note.parent / ".obsidian/app.json"
        ctl.atomic_json(vault_config, {"user_setting": True})
        profile = ctl.state_root() / "obsidian" / item["id"] / "obsidian.json"
        ctl.atomic_json(profile, {"custom": True, "vaults": {"other": {"open": False}}})
        ctl.notes("s2")
        config = ctl.read_json(profile)
        self.assertTrue(config["custom"])
        self.assertIn("other", config["vaults"])
        self.assertTrue(config["vaults"][item["id"].replace("-", "")[:16]]["open"])
        vault_state = profile.parent / f"{item['id'].replace('-', '')[:16]}.json"
        self.assertEqual(ctl.read_json(vault_state), {})
        arguments = self.spawn.call_args.args[0]
        self.assertIn(f"--class=context-notes-{item['id']}", arguments)
        self.assertEqual(arguments[-1], f"--class=context-notes-{item['id']}")
        self.assertEqual(note.read_text(), "User notes\n")
        self.assertEqual(ctl.read_json(vault_config), {"user_setting": True})
        workspace = ctl.read_json(note.parent / ".obsidian/workspace.json")
        self.assertEqual(workspace["main"]["children"][0]["children"][0]["state"]["state"]["file"], "Home.md")
        with self.assertRaises(ctl.ContextError):
            ctl.create("Projects/Alpha")
        self.assertEqual(note.read_text(), "User notes\n")

    def test_notes_reuses_window(self):
        item = self.mapped()
        self.run.return_value.stdout = json.dumps([{
            "class": f"context-notes-{item['id']}",
            "workspace": {"name": "special:session-s2-notes"}, "address": "0x123",
        }])
        ctl.notes("s2")
        self.spawn.assert_not_called()

    def test_notes_routes_existing_window_silently(self):
        item = self.mapped()
        self.run.side_effect = [
            Mock(returncode=0, stdout=json.dumps([{
                "class": f"context-notes-{item['id']}", "address": "0x123",
                "workspace": {"name": "other"},
            }]), stderr=""),
            Mock(returncode=0, stdout="ok", stderr=""),
        ]
        ctl.notes("s2")
        self.spawn.assert_not_called()
        statement = self.run.call_args.args[0][2]
        self.assertIn("follow=false", statement)
        self.assertIn(ctl.lua_string("special:session-s2-notes"), statement)

    def test_process_profile_reads_rewritten_electron_title(self):
        identifier = "2f34ab31-ad7e-44ee-b2e9-e5288ed11109"
        profile = str(ctl.state_root() / "obsidian" / identifier)
        title = f"electron --user-data-dir={profile} --class=context-notes-{identifier} app.asar\0"
        with patch.object(Path, "read_bytes", return_value=title.encode()):
            self.assertEqual(ctl.process_profile(123), profile)

    def test_process_profile_reads_exact_argument(self):
        profile = str(ctl.state_root() / "obsidian/example")
        with patch.object(Path, "read_bytes", autospec=True, return_value=(
                b"/bin/obsidian\0--other\0--user-data-dir=" + os.fsencode(profile) + b"\0")) as read:
            self.assertEqual(ctl.process_profile(123), profile)
            read.assert_called_once_with(Path("/proc/123/cmdline"))
        for arguments in (b"obsidian\0--other=--user-data-dir=/tmp/x\0",
                          b"obsidian\0--user-data-dir\0/tmp/x\0",
                          b"obsidian\0--user-data-dir=/tmp/x\0--user-data-dir=/tmp/y\0"):
            with self.subTest(arguments=arguments), patch.object(Path, "read_bytes", return_value=arguments):
                self.assertIsNone(ctl.process_profile(123))

    def test_process_profile_rejects_invalid_pid_and_missing_process(self):
        with patch.object(Path, "read_bytes") as read:
            for pid in (None, True, False, 0, -1, "123", "../123", 1.5):
                with self.subTest(pid=pid):
                    self.assertIsNone(ctl.process_profile(pid))
            read.assert_not_called()
        for error in (FileNotFoundError(), PermissionError()):
            with patch.object(Path, "read_bytes", side_effect=error):
                self.assertIsNone(ctl.process_profile(123))

    def test_notes_reuses_wayland_profile_and_prefers_workspace_address(self):
        item = self.mapped()
        profile = str(ctl.state_root() / "obsidian" / item["id"])
        self.run.return_value.stdout = json.dumps([{
            "class": "md.Obsidian", "pid": 123, "address": "0x123",
            "workspace": {"address": "special:session-s2-notes", "name": "renamed"},
        }])
        with patch.object(ctl, "process_profile", return_value=profile) as lookup:
            ctl.notes("s2")
        lookup.assert_called_once_with(123)
        self.run.assert_called_once()
        self.spawn.assert_not_called()

    def test_notes_routes_wayland_profile_despite_matching_display_name(self):
        item = self.mapped()
        profile = str(ctl.state_root() / "obsidian" / item["id"])
        self.run.side_effect = [
            Mock(returncode=0, stdout=json.dumps([{
                "class": "md.Obsidian", "pid": 123, "address": "0x123",
                "workspace": {"address": "special:other", "name": "special:session-s2-notes"},
            }]), stderr=""),
            Mock(returncode=0, stdout="ok", stderr=""),
        ]
        with patch.object(ctl, "process_profile", return_value=profile):
            ctl.notes("s2")
        self.assertIn("follow=false", self.run.call_args.args[0][2])
        self.spawn.assert_not_called()

    def test_profile_ownership_requires_exact_path(self):
        item = self.mapped()
        profile = str(ctl.state_root() / "obsidian" / item["id"])
        for other in (None, profile + "-other", profile + "/", "/other" + profile):
            with self.subTest(profile=other), patch.object(ctl, "process_profile", return_value=other):
                self.assertIsNone(ctl.note_context({"class": "md.Obsidian", "pid": 123}, [item]))

    def test_notes_preserves_existing_local_vault_state(self):
        item = self.mapped()
        vault_state = ctl.state_root() / "obsidian" / item["id"] / f"{item['id'].replace('-', '')[:16]}.json"
        ctl.atomic_json(vault_state, {"existing": True})
        ctl.notes("s2")
        self.assertEqual(ctl.read_json(vault_state), {"existing": True})

    def test_rename_blocks_wayland_descendant_vault_without_live_runtime(self):
        parent = ctl.create("Projects")
        child = ctl.create("Projects/Alpha")
        self.run.return_value.stdout = json.dumps([{"class": "md.Obsidian", "pid": 123}])
        with patch.object(ctl, "process_profile", return_value=str(ctl.state_root() / "obsidian" / child["id"])):
            with self.assertRaisesRegex(ctl.ContextError, "Close note vault"):
                ctl.rename_context(parent["id"], "Renamed")
        self.assertEqual(ctl.find_context(child["id"])["name"], "Projects/Alpha")

    def test_reconcile_ignores_unrelated_obsidian(self):
        self.mapped()
        self.run.return_value.stdout = json.dumps([{"class": "md.Obsidian", "pid": 123}])
        with patch.object(ctl, "process_profile", return_value="/other/obsidian"):
            ctl.reconcile_notes(ctl.catalog()["contexts"])
        self.run.assert_called_once()
        self.spawn.assert_not_called()

    def test_reconcile_rechecks_stale_mapping_and_runtime(self):
        item = self.mapped()
        contexts = ctl.catalog()["contexts"]
        self.run.return_value.stdout = json.dumps([{
            "class": f"context-notes-{item['id']}", "address": "0x123", "workspace": {"name": "other"},
        }])
        self.runtime([])
        ctl.reconcile_notes(contexts)
        self.assertEqual(self.run.call_count, 1)
        self.runtime([{"id": "s2", "name": "Projects/Alpha"}], "s2")
        ctl.save_state({"mappings": {}, "last_active": None})
        ctl.reconcile_notes(contexts)
        self.assertEqual(self.run.call_count, 2)
        self.spawn.assert_not_called()

    def test_watch_routes_late_wayland_window_to_inactive_owner_without_lock(self):
        item = self.mapped()
        profile = str(ctl.state_root() / "obsidian" / item["id"])
        inspections = 0
        sleeps = 0

        def backend(arguments, **kwargs):
            nonlocal inspections
            # Slow compositor calls must not block CLI mutations behind watch's lock.
            with (ctl.state_root() / "contextctl.lock").open("a") as other:
                ctl.fcntl.flock(other, ctl.fcntl.LOCK_EX | ctl.fcntl.LOCK_NB)
            self.assertEqual(kwargs["timeout"], 3)
            if arguments[1] == "-j":
                inspections += 1
                value = [] if inspections == 1 else [{
                    "class": "md.Obsidian", "pid": 123, "address": "0x123",
                    "workspace": {"address": "special:session-s3-notes", "name": "elsewhere"},
                }]
                return Mock(returncode=0, stdout=json.dumps(value), stderr="")
            statement = arguments[2]
            self.assertIn(ctl.lua_string("special:session-s2-notes"), statement)
            self.assertIn("follow=false", statement)
            self.assertNotIn("show_special", statement)
            self.assertNotIn(".switch", statement)
            return Mock(returncode=0, stdout="ok", stderr="")

        def tick(_):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 1:
                self.runtime([{"id": "s2", "name": "Projects/Alpha", "window_count": 1},
                              {"id": "s3", "name": "Other"}], "s3")
            else:
                raise KeyboardInterrupt

        self.run.side_effect = backend
        with patch.object(ctl, "process_profile", return_value=profile), patch.object(ctl.time, "sleep", side_effect=tick):
            with self.assertRaises(KeyboardInterrupt):
                ctl.watch()
        self.assertEqual(inspections, 2)
        self.assertEqual(self.run.call_count, 3)
        self.spawn.assert_not_called()

    def test_watch_reports_compositor_timeout_without_launching(self):
        self.mapped()
        self.run.side_effect = subprocess.TimeoutExpired("hyprctl", 3)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors), patch.object(ctl.time, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                ctl.watch()
        self.assertIn("timed out", errors.getvalue())
        self.spawn.assert_not_called()

    def test_terminal_and_fallback(self):
        item = self.mapped()
        ctl.terminal("s2")
        arguments = self.spawn.call_args.args[0]
        self.assertIn(f"context-{item['id']}", arguments)
        self.assertEqual(arguments[-4:], ["create-tmux-session", str(ctl.root() / "Projects/Alpha"),
                                         f"context-{item['id']}", "--attach"])
        self.assertIn(f"CONTEXT_DIRECTORY={ctl.root() / 'Projects/Alpha'}", arguments)
        self.assertIn(f"CONTEXT_ID={item['id']}", arguments)
        self.runtime([{"id": "s99", "name": "Runtime only"}], "s99")
        ctl.terminal("s99")
        self.assertIn("desktop-test-signature-s99", self.spawn.call_args.args[0])

    def test_catalog_atomic_unchanged_and_activation(self):
        item = self.mapped()
        value = ctl.publish(record_activation=True)
        self.assertEqual(value["active_context"], item["id"])
        self.assertEqual(value["contexts"][0]["window_count"], 3)
        self.assertEqual(ctl.local_state()["last_active"], item["id"])
        path = ctl.runtime_path("desktop-contexts")
        before = path.stat().st_mtime_ns
        ctl.publish(record_activation=True)
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(ctl.read_json(path), value)
        self.runtime([])
        ctl.publish(record_activation=True)
        self.assertIsNone(ctl.local_state()["last_active"])
        self.run.assert_not_called()

    def test_new_compositor_does_not_restore(self):
        self.mapped()
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "new"}):
            value = ctl.publish(record_activation=True)
        self.assertIsNone(value["active_context"])
        self.assertIsNone(value["contexts"][0]["runtime_id"])
        self.run.assert_not_called()

    def test_rename_repository_context_rejected(self):
        item = ctl.create("Repo", "work/Repo")
        metadata = ctl.root() / "Repo/.context/context.json"
        data = ctl.read_json(metadata)
        data["repositories"] = [{"path": "work/Repo"}]
        ctl.atomic_json(metadata, data)
        with self.assertRaisesRegex(ctl.ContextError, "Git sync paths"):
            ctl.rename_context(item["id"], "Other")
        self.assertTrue((ctl.root() / "Repo/.context/context.json").exists())

    def test_rename_preserves_id_and_notes(self):
        item = ctl.create("Projects/Alpha")
        ctl.rename_context(item["id"], "Beta")
        renamed = ctl.find_context(item["id"])
        self.assertEqual(renamed["name"], "Projects/Beta")
        self.assertTrue((Path(renamed["path"]) / ".context/notes/Home.md").read_text().startswith("# Alpha\n"))

    def test_rename_rejects_live_or_descendant_vault(self):
        item = self.mapped()
        with self.assertRaisesRegex(ctl.ContextError, "Close"):
            ctl.rename_context(item["id"], "Beta")
        self.runtime([])
        self.run.return_value.stdout = json.dumps([{"class": f"context-notes-{item['id']}"}])
        with self.assertRaisesRegex(ctl.ContextError, "Close"):
            ctl.rename_context(item["id"], "Beta")

    def test_cli_stdout_and_errors(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(ctl.main(["create", "Alpha"]), 0)
        self.assertEqual(output.getvalue(), "ok\n")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(ctl.main(["list"]), 0)
        self.assertEqual(json.loads(output.getvalue()), ctl.read_json(ctl.runtime_path("desktop-contexts")))
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            self.assertEqual(ctl.main(["open", "unknown"]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Unknown context", errors.getvalue())

    def test_backend_failure_is_error(self):
        item = self.mapped()
        self.run.return_value = Mock(returncode=1, stdout="", stderr="backend unavailable")
        with self.assertRaisesRegex(ctl.ContextError, "backend unavailable"):
            ctl.open_context(item["id"])

    def test_backend_zero_exit_lua_error_is_error(self):
        item = self.mapped()
        self.run.return_value = Mock(returncode=0, stdout="evaluation failed: bad call", stderr="")
        with self.assertRaisesRegex(ctl.ContextError, "evaluation failed"):
            ctl.open_context(item["id"])

    def test_renamed_home_does_not_disable_other_contexts(self):
        item = self.mapped("Alpha")
        ctl.create("Beta")
        home = ctl.root() / "Alpha/.context/notes/Home.md"
        home.rename(home.with_name("My notes.md"))
        self.assertEqual(len(ctl.publish()["contexts"]), 2)
        ctl.notes("s2")
        self.assertTrue(home.with_name("My notes.md").exists())
        self.assertFalse(home.exists())
        self.assertEqual(ctl.find_context(item["id"])["name"], "Alpha")

    def test_delayed_launch_rejects_closed_runtime(self):
        self.mapped()
        for launch in (ctl.notes, ctl.terminal):
            with self.subTest(launch=launch.__name__), self.assertRaisesRegex(ctl.ContextError, "closed"):
                launch("s99")
        self.spawn.assert_not_called()

    def test_failed_atomic_replace_preserves_file(self):
        path = self.base / "atomic.json"
        ctl.atomic_json(path, {"old": True})
        with patch.object(ctl.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                ctl.atomic_json(path, {"new": True})
        self.assertEqual(ctl.read_json(path), {"old": True})
        self.assertEqual(list(self.base.glob(".contextctl-*")), [])

    def test_rename_write_failure_rolls_back_directory(self):
        item = ctl.create("Projects/Alpha")
        with patch.object(ctl, "atomic_json", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                ctl.rename_context(item["id"], "Beta")
        self.assertEqual(ctl.find_context(item["id"])["name"], "Projects/Alpha")

    def test_rename_parent_rejects_live_descendant(self):
        parent = ctl.create("Projects")
        self.mapped("Projects/Alpha")
        with self.assertRaisesRegex(ctl.ContextError, "descendant"):
            ctl.rename_context(parent["id"], "Renamed")

    def test_watch_polls_without_launching_and_keeps_catalog(self):
        self.mapped()
        with patch.object(ctl.time, "sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                ctl.watch()
        self.assertTrue(ctl.runtime_path("desktop-contexts").exists())
        self.run.assert_called_once_with(["hyprctl", "-j", "clients"], capture_output=True, text=True, timeout=3)
        self.spawn.assert_not_called()

    def test_mutation_lock_excludes_other_file_descriptors(self):
        with ctl.mutation_lock():
            with (ctl.state_root() / "contextctl.lock").open("a") as other:
                with self.assertRaises(BlockingIOError):
                    ctl.fcntl.flock(other, ctl.fcntl.LOCK_EX | ctl.fcntl.LOCK_NB)
        with (ctl.state_root() / "contextctl.lock").open("a") as other:
            ctl.fcntl.flock(other, ctl.fcntl.LOCK_EX | ctl.fcntl.LOCK_NB)


if __name__ == "__main__":
    unittest.main()
