"""Native tmux recovery contracts; every server/socket/state root is test-owned."""

import copy
import json
import os
from pathlib import Path
import pty
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import contextctl as ctl
import persistence as p
from test_checkpoint_store import Changes, stats


TMUX = os.environ.get("PERSISTENCE_TMUX") or shutil.which("tmux")


class CommandCaptureTests(unittest.TestCase):
    def test_noninteractive_commands_disconnect_inherited_terminal_stdin(self):
        reply = subprocess.CompletedProcess(["fixture"], 0, "ready\n", "")
        with patch.object(p.subprocess, "run", return_value=reply) as command:
            self.assertEqual(p.run(["fixture"]), "ready")
        self.assertEqual(command.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_explicit_stdin_is_preserved(self):
        reply = subprocess.CompletedProcess(["fixture"], 0, "ready", "")
        with patch.object(p.subprocess, "run", return_value=reply) as command:
            p.run(["fixture"], stdin=subprocess.PIPE)
        self.assertEqual(command.call_args.kwargs["stdin"], subprocess.PIPE)

    def test_explicit_input_does_not_conflict_with_default_stdin(self):
        reply = subprocess.CompletedProcess(["fixture"], 0, "ready", "")
        with patch.object(p.subprocess, "run", return_value=reply) as command:
            p.run(["fixture"], input="payload")
        self.assertNotIn("stdin", command.call_args.kwargs)
        self.assertEqual(command.call_args.kwargs["input"], "payload")


class EditorRpcTests(unittest.TestCase):
    @staticmethod
    def snapshot():
        return {"version": 2, "editor_id": "editor-id", "contents_encoding": "base64", "contents": {}}

    @staticmethod
    def reply(stdout, stderr="", code=0):
        return subprocess.CompletedProcess(["nvim"], code, stdout, stderr)

    def test_successful_snapshot_uses_one_rpc(self):
        snapshot = self.snapshot()
        with patch.object(p.subprocess, "run", return_value=self.reply(json.dumps(snapshot))) as rpc:
            self.assertEqual(p.editor_snapshot("/fixture/editor.sock"), snapshot)
        self.assertEqual(rpc.call_count, 1, "normal no-op capture must not add exporter/RPC retries")
        self.assertEqual(rpc.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_empty_and_truncated_successful_replies_retry_memory_capture(self):
        snapshot = self.snapshot()
        replies = [self.reply(""), self.reply('{"version":'), self.reply(json.dumps(snapshot))]
        with patch.object(p.subprocess, "run", side_effect=replies) as rpc, patch.object(p.time, "sleep"):
            self.assertEqual(p.editor_snapshot("/fixture/editor.sock"), snapshot)
        self.assertEqual(rpc.call_count, 3)
        self.assertTrue(all(call.kwargs["timeout"] <= 15 for call in rpc.call_args_list))
        self.assertTrue(all(call.kwargs["stdin"] == subprocess.DEVNULL for call in rpc.call_args_list))

    def test_persistent_invalid_reply_is_bounded_and_reports_native_diagnostics(self):
        with patch.object(p.subprocess, "run", return_value=self.reply("", "native reply omitted")) as rpc, \
                patch.object(p.time, "sleep"), self.assertRaisesRegex(p.CheckpointError, "native reply omitted"):
            p.editor_snapshot("/fixture/editor.sock")
        self.assertEqual(rpc.call_count, 3)

    def test_native_errors_and_schema_mismatch_are_not_retried_or_accepted(self):
        for reply, message in ((self.reply("", "adapter rejected capture", 2), "adapter rejected capture"),
                               (self.reply("null"), "schema"),
                               (self.reply('{"version":1}'), "schema")):
            with self.subTest(message=message), patch.object(p.subprocess, "run", return_value=reply) as rpc, \
                    self.assertRaisesRegex(p.CheckpointError, message):
                p.editor_snapshot("/fixture/editor.sock")
            self.assertEqual(rpc.call_count, 1)

    def test_reply_retries_share_one_total_deadline(self):
        with patch.object(p.subprocess, "run", return_value=self.reply("")) as rpc, \
                patch.object(p.time, "monotonic", side_effect=[0, 0, 16]), \
                self.assertRaisesRegex(p.CheckpointError, "timed out"):
            p.editor_snapshot("/fixture/editor.sock")
        self.assertEqual(rpc.call_count, 1)


class ProgramReadinessTests(unittest.TestCase):
    def test_shell_restoration_waits_until_tmux_child_executes_shell(self):
        tm = Mock()
        tm.rows.side_effect = [[{"pane_id": "%0", "pane_current_command": "tmux"}],
                               [{"pane_id": "%0", "pane_current_command": "sh"}]]
        with patch.object(p.time, "sleep"):
            p.await_program(tm, "%0", {"command": "sh"}, ["env", "/bin/sh"])
        self.assertEqual(tm.rows.call_count, 2, "fork completion is not process exec acknowledgement")

    def test_shell_that_never_executes_is_explicit_recovery_failure(self):
        tm = Mock()
        tm.rows.return_value = [{"pane_id": "%0", "pane_current_command": "tmux"}]
        with patch.object(p.time, "monotonic", side_effect=[0, 0, 6]), patch.object(p.time, "sleep"), \
                self.assertRaisesRegex(p.CheckpointError, "process.*timed out"):
            p.await_program(tm, "%0", {"command": "sh"}, ["env", "/bin/sh"])
        self.assertEqual(tm.rows.call_count, 1)


class PersistenceTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        if not TMUX or not shutil.which(TMUX):
            self.skipTest("tmux unavailable; set PERSISTENCE_TMUX")
        if os.environ.get("PERSISTENCE_NATIVE_TESTS") != "1":
            self.skipTest("set PERSISTENCE_NATIVE_TESTS=1 for isolated native capture")
        self.temp = tempfile.TemporaryDirectory(prefix="persistence-tests-", dir="/tmp/opencode")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        env = {"HOME": str(self.home), "CONTEXT_ROOT": str(self.base / "contexts"),
               "XDG_STATE_HOME": str(self.base / "state"), "XDG_CONFIG_HOME": str(self.base / "config"),
               "XDG_DATA_HOME": str(self.base / "data"), "XDG_CACHE_HOME": str(self.base / "cache"),
               "XDG_RUNTIME_DIR": str(self.base / "runtime"), "TMUX": "", "TMUX_TMPDIR": str(self.base),
               "HYPRLAND_INSTANCE_SIGNATURE": "", "SHELL": "/bin/sh", "TERM": "xterm-256color",
               "PERSISTENCE_TMUX": TMUX,
               "PATH": str(Path(TMUX).parent) + os.pathsep + os.environ["PATH"]}
        self.enterContext(patch.dict(os.environ, env))
        self.notices = self.enterContext(patch.object(p, "notify"))
        self.tm = p.Tmux(self.base / "source.sock")
        self.dest = p.Tmux(self.base / "restore.sock")
        self.servers = [self.tm, self.dest]
        self.addCleanup(self.kill_servers)
        # Discovery must never scan /tmp/tmux-$UID or connect to user servers.
        self.discovery = self.enterContext(patch.object(p, "sockets", return_value=[self.tm]))
        self.a = self.context("Alpha context")
        self.b = self.context("Beta context")
        self.last_save = 0

    def kill_servers(self):
        for tm in self.servers:
            subprocess.run([TMUX, "-S", tm.socket, "set-option", "-su", "@persistence-checkpoint"],
                           capture_output=True)
            subprocess.run([TMUX, "-S", tm.socket, "kill-server"], capture_output=True)

    def context(self, name):
        return ctl.find_context(ctl.create(name)["id"])

    def session(self, name, context=None, cwd=None, tm=None):
        tm = tm or self.tm
        cwd = cwd or (context["path"] if context else self.home)
        result = p.run([TMUX, "-S", tm.socket, "-f", "/dev/null", "new-session", "-d",
                        "-x", "160", "-y", "50", "-P", "-F", "#{pane_id}",
                        "-s", name, "-c", cwd, "/bin/sh"])
        tm.call("set-option", "-g", "default-shell", "/bin/sh")
        tm.call("set-option", "-g", "automatic-rename", "off")
        if context:
            tm.call("set-option", "-t", name, "@persistence-context", context["id"])
        self.wait_command(tm, result, "sh")
        return result

    def new_server(self, name):
        tm = p.Tmux(self.base / (name + ".sock"))
        self.servers.append(tm)
        return tm

    def save(self, reason="periodic", context=None, rapid=False):
        # Most contracts exercise distinct plugin timestamp generations. Separate
        # rapid-save test below retains the same-second regression assertion.
        if not rapid and self.last_save:
            time.sleep(max(0, 1.05 - (time.monotonic() - self.last_save)))
        try:
            p.checkpoint(reason, context["id"] if context else None, self.tm.socket)
        except p.CheckpointError as exc:
            exc.add_note(f"Coordinator diagnostics: {self.notices.call_args_list}")
            raise
        finally:
            self.last_save = time.monotonic()

    def saved(self, context=None):
        base, manifest = p.latest(context or self.a)
        return base, manifest, ctl.read_json(base / "tmux.json")

    def recover(self, context=None, tm=None):
        base, manifest = p.latest(context or self.a)
        errors = []
        mapping = p.restore_tmux(base, manifest, context or self.a, errors, tm or self.dest)
        self.assertEqual(errors, [], "scoped reconstruction must complete without recovery errors")
        return mapping

    def captured(self, tm=None):
        return [value for _, _, value in p.capture_tmux(tm or self.dest, ctl.scan())]

    def wait_command(self, tm, pane, command):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            actual = tm.call("display-message", "-p", "-t", pane, "#{pane_current_command}")
            if actual == command:
                return
            time.sleep(.05)
        self.fail(f"pane {pane} command {actual!r}, expected {command!r}")

    @staticmethod
    def topology(sessions):
        result = copy.deepcopy(sessions)
        for session in result:
            session.pop("observed_id", None)
            for window in session["windows"]:
                # Native layout pane IDs change on a different server; geometry/order must not.
                identities = {pane["observed_id"].lstrip("%"): pane["id"] for pane in window["panes"]}
                window["layout"] = re.sub(r"(\d+x\d+,\d+,\d+,)(\d+)(?=[,}\]]|$)",
                                          lambda match: match[1] + identities[match[2]],
                                          window["layout"].split(",", 1)[1])
                for pane in window["panes"]:
                    pane.pop("observed_id", None)
                    pane.pop("local", None)
        return result

    def complex_session(self):
        first = self.session("alpha session", self.a)
        # Nondefault index exercises real remapping; index zero has its own test.
        self.tm.call("move-window", "-s", "alpha session:0", "-t", "alpha session:2")
        path = Path(self.a["path"]) / "directory with spaces"
        path.mkdir()
        second = self.tm.call("split-window", "-h", "-P", "-F", "#{pane_id}", "-t", first,
                              "-c", path, "/bin/sh")
        third = self.tm.call("split-window", "-v", "-P", "-F", "#{pane_id}", "-t", second,
                             "-c", self.a["path"], "/bin/sh")
        self.tm.call("rename-window", "-t", first, "code and notes")
        self.tm.call("new-window", "-d", "-t", "alpha session:4", "-n", "other window",
                     "-c", path, "/bin/sh")
        self.tm.call("select-pane", "-t", third, "-T", "selected pane title")
        self.tm.call("select-window", "-t", first)
        self.tm.call("resize-pane", "-Z", "-t", third)
        for pane in self.tm.rows("list-panes", ["pane_id"], "-a"):
            self.wait_command(self.tm, pane["pane_id"], "sh")
        return first, second, third

    def test_default_zero_window_index_restores(self):
        self.session("default index", self.a)
        self.save()
        self.recover()

    def test_stale_dead_socket_does_not_prevent_crash_reconstruction(self):
        self.session("stale socket recovery", self.a)
        self.save()
        with socket.socket(socket.AF_UNIX) as stale:
            stale.bind(self.dest.socket)
        self.assertTrue(Path(self.dest.socket).is_socket())
        self.recover()
        self.assertEqual(self.dest.call("list-sessions", "-F", "#{session_name}"), "stale socket recovery")
        self.assertEqual(self.dest.call("show-options", "-s", "-v", "@persistence-native"), "1")

    def test_same_physical_window_linked_twice_preserves_indices_and_selection(self):
        self.session("duplicate links", self.a)
        self.tm.call("link-window", "-d", "-s", "duplicate links:0", "-t", "duplicate links:2")
        self.save()
        saved = self.saved()[2]
        self.assertEqual(len(saved[0]["windows"]), 2)
        self.assertTrue(all(len(window["panes"]) == 1 for window in saved[0]["windows"]))
        self.recover()
        self.assertEqual(self.topology(self.captured()), self.topology(saved))

    def test_grouped_windows_restore_independent_active_window_and_shared_processes(self):
        self.session("group base", self.a)
        self.tm.call("new-window", "-d", "-t", "group base:2", "-c", self.a["path"], "/bin/sh")
        self.tm.call("new-session", "-d", "-s", "group peer", "-t", "group base")
        self.tm.call("select-window", "-t", "group base:0")
        self.tm.call("select-window", "-t", "group peer:2")
        self.save()
        self.recover()
        sessions = self.dest.rows("list-sessions", ["session_name", "session_group"])
        self.assertEqual(len({s["session_group"] for s in sessions}), 1)
        self.assertTrue(sessions[0]["session_group"])
        self.assertEqual(self.dest.call("display-message", "-p", "-t", "group base:", "#{window_index}"), "0")
        self.assertEqual(self.dest.call("display-message", "-p", "-t", "group peer:", "#{window_index}"), "2")
        windows = self.dest.rows("list-windows", ["window_id"], "-a")
        self.assertEqual(len(windows), 4)
        self.assertEqual(len({w["window_id"] for w in windows}), 2)

    def test_rapid_checkpoint_publishes_without_plugin_timestamp_collision(self):
        self.session("alpha", self.a)
        self.align_clock()
        self.save()
        old = self.saved()[1]["id"]
        self.save(rapid=True)
        self.assertEqual(self.saved()[1]["id"], old, "unchanged rapid save must be a no-op")
        self.tm.call("rename-window", "-t", "alpha:0", "changed")
        self.save(rapid=True)
        self.assertNotEqual(self.saved()[1]["id"], old)

    def test_coordinator_noop_has_zero_transient_checkpoint_writes(self):
        self.session("no-op", self.a)
        self.save()
        before = stats(self.base)
        audit = Changes(self.base)
        with patch.object(p.store, "atomic", side_effect=AssertionError("no-op publication")), \
                patch.object(ctl, "atomic_json", side_effect=AssertionError("no-op registry write")):
            for _ in range(12):
                self.save(rapid=True)
        self.assertEqual(audit.finish(), b"", "no-op performed temporary writes/deletions")
        self.assertEqual(stats(self.base), before)

    def test_successful_changed_saves_only_notify_new_distinct_warnings(self):
        self.session("warnings", self.a)
        capture = p.adapter_capture
        warnings = ["Git snapshot objects not bundled"] * 20

        def adapter(*args):
            capture(*args)
            args[-1].extend(warnings)

        with patch.object(p, "adapter_capture", side_effect=adapter):
            self.save()
            self.notices.assert_called_once_with(["Git snapshot objects not bundled"])
            first = self.saved()[1]["id"]
            self.notices.reset_mock()
            self.tm.call("rename-window", "-t", "warnings:0", "changed")
            self.save(rapid=True)
            self.assertNotEqual(self.saved()[1]["id"], first)
            self.notices.assert_not_called()
            warnings.append("New unsupported process")
            self.save(rapid=True)
            self.notices.assert_called_once_with(["New unsupported process"])

    def test_chat_change_defers_only_periodic_saves_without_replacing_checkpoint(self):
        self.session("chat-busy", self.a)
        self.save()
        previous = self.saved()[1]["id"]
        busy = p.chats.ChatChangedDuringCheckpoint("Chat changed during checkpoint; retry capture")
        with patch.object(p, "adapter_capture", side_effect=busy):
            self.save(rapid=True)
            self.assertEqual(self.saved()[1]["id"], previous)
            self.notices.assert_not_called()
            for reason in ("manual", "close", "shutdown", "pre-kill"):
                with self.subTest(reason=reason), self.assertRaises(p.CheckpointError):
                    self.save(reason, rapid=True)
                self.assertEqual(self.saved()[1]["id"], previous)
                self.assertIn("Chat changed", self.notices.call_args.args[0][0])

        self.notices.reset_mock()
        self.tm.call("rename-window", "-t", "chat-busy:0", "changed")
        self.save(rapid=True)
        self.assertNotEqual(self.saved()[1]["id"], previous)
        self.notices.assert_not_called()

    def test_v1_migration_validates_then_reclaims_generations_and_raw_scratch(self):
        self.session("migrate", self.a)
        self.save("pre-kill")
        base, current, _ = self.saved()
        files = {name: (base / name).read_bytes() for name in current["artifacts"]}
        storage = p.checkpoint_store(self.a)
        shutil.rmtree(storage.directory)
        shutil.rmtree(storage.local)
        parent = None
        for sequence in range(2):
            generation = f"generations/{sequence}-source"
            destination = storage.directory / generation
            artifacts = {}
            for name, data in files.items():
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                artifacts[name] = {"size": len(data), "sha256": p.store.sha(data)}
            manifest = dict(current, version=1, id=generation, parent=parent,
                            created_ns=sequence + 1, artifacts=artifacts)
            ctl.atomic_json(destination / "manifest.json", manifest)
            ctl.atomic_json(storage.directory / "heads/source.json", {
                "generation": generation, "created_ns": sequence + 1,
                "sha256": p.digest(destination / "manifest.json")})
            parent = generation
        (storage.directory / ("generations/123-" + p.device() + "-unpublished-candidate")).mkdir()
        raw = p.local_root() / "resurrect/server/captures/unpublished"
        raw.mkdir(parents=True)
        (raw / "raw.txt").write_text("scratch")
        self.assertEqual(p.latest(self.a)[1]["version"], 1)
        selected_artifact = storage.directory / parent / "tmux.json"
        selected_artifact.write_bytes(b"corrupt incoming v1")
        with self.assertRaises(p.CheckpointError):
            self.save(rapid=True)
        self.assertFalse((storage.directory / "current.json").exists())
        self.assertTrue((storage.directory / "generations").exists())
        selected_artifact.write_bytes(files["tmux.json"])
        self.save()
        base, manifest, _ = self.saved()
        self.assertEqual(manifest["version"], 2)
        p.validate(base, manifest)
        self.assertFalse((storage.directory / "generations").exists())
        self.assertFalse((storage.directory / "heads").exists())
        self.assertFalse((p.local_root() / "resurrect").exists())
        self.assertTrue(ctl.read_json(p.local_root() / f"retained-{self.a['id']}.json")["sessions"])
        self.recover()

    @unittest.skipUnless(os.environ.get("PERSISTENCE_NATIVE_TESTS") == "1", "native editor fixture opt-in")
    def test_native_editor_rpc_from_terminal_stdin_preserves_capture_and_ready_ack(self):
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        original = subprocess.run
        observed = []

        def terminal_parent(args, **kwargs):
            if "--remote-expr" in args:
                observed.append(kwargs.get("stdin"))
                # Model the supervisor's inherited terminal only when the
                # production caller did not explicitly choose noninteractive I/O.
                kwargs.setdefault("stdin", slave)
            return original(args, **kwargs)

        with patch.object(p.subprocess, "run", side_effect=terminal_parent):
            self.test_real_editor_ram_capture_chunk_isolation_and_exit_without_publication_deadlock()
        self.assertTrue(observed)
        self.assertTrue(all(stdin == subprocess.DEVNULL for stdin in observed),
                        "all snapshot, readiness and recovery RPC clients must disconnect terminal stdin")

    @unittest.skipUnless(os.environ.get("PERSISTENCE_NATIVE_TESTS") == "1", "native editor fixture opt-in")
    def test_native_editor_capture_survives_lost_and_truncated_cli_replies(self):
        original = subprocess.run
        injected = []

        def transport(args, **kwargs):
            if "--remote-expr" in args and ".snapshot()" in args[-1] and len(injected) < 2:
                output = "" if not injected else '{"version":'
                injected.append(output)
                return subprocess.CompletedProcess(args, 0, output, "")
            return original(args, **kwargs)

        with patch.object(p.subprocess, "run", side_effect=transport):
            # Keep every original recovery/chunk/no-op/exit assertion. Inject
            # transport loss only; the successful reply comes from real Neovim.
            self.test_real_editor_ram_capture_chunk_isolation_and_exit_without_publication_deadlock()
        self.assertEqual(injected, ["", '{"version":'])

    def test_persistent_editor_reply_failure_preserves_current_without_writes(self):
        self.session("bad editor reply", self.a)
        self.save()
        before = self.saved()[1]
        snapshot = stats(self.base)
        audit = Changes(self.base)
        original_capture, original_run = p.capture_tmux, subprocess.run
        attempts = []

        def editor(*args):
            values = original_capture(*args)
            pane = values[0][2]["windows"][0]["panes"][0]
            pane["command"] = "nvim"
            pane["local"].update({"@persistence-editor": "editor-id", "@persistence-editor-socket": "/fixture/editor.sock"})
            return values

        def transport(args, **kwargs):
            if "--remote-expr" in args and ".snapshot()" in args[-1]:
                attempts.append(args)
                return subprocess.CompletedProcess(args, 0, "", "native reply omitted")
            return original_run(args, **kwargs)

        with patch.object(p, "capture_tmux", side_effect=editor), \
                patch.object(p.subprocess, "run", side_effect=transport), self.assertRaises(p.CheckpointError):
            self.save(rapid=True)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(self.saved()[1], before)
        self.assertIn("native reply omitted", str(self.notices.call_args_list))
        self.assertEqual(audit.finish(), b"", "failed capture wrote temporary checkpoint state")
        self.assertEqual(stats(self.base), snapshot)

    @unittest.skipUnless(os.environ.get("PERSISTENCE_NATIVE_TESTS") == "1", "native editor fixture opt-in")
    def test_real_editor_ram_capture_chunk_isolation_and_exit_without_publication_deadlock(self):
        (self.base / "runtime").mkdir(mode=0o700)
        pane = self.session("editor", self.a)
        adapter = Path(__file__).resolve().parents[2] / "development/nvim/config/lua/context_persistence.lua"
        init = self.base / "editor-init.lua"
        init.write_text("vim.o.swapfile=false; package.loaded.context_persistence=dofile(" + p.lua_value(str(adapter))
                        + "); require('context_persistence').setup()")
        nvim = shutil.which("nvim")
        self.assertIsNotNone(nvim)
        self.tm.call("send-keys", "-t", pane, shlex.join([nvim, "--headless", "-u", str(init), "-i", "NONE", "-n"]), "Enter")
        self.wait_command(self.tm, pane, "nvim")
        deadline = time.monotonic() + 5
        while True:
            endpoint = self.tm.call("show-options", "-p", "-qv", "-t", pane, "@persistence-editor-socket")
            if endpoint and Path(endpoint).is_socket():
                break
            self.assertLess(time.monotonic(), deadline, self.tm.call("capture-pane", "-p", "-t", pane))
            time.sleep(.03)

        def rpc(code):
            return p.run([nvim, "--server", endpoint, "--remote-expr", 'luaeval(' + json.dumps(code) + ')'])

        rpc("(function() local lines={}; for i=1,512 do lines[i]=tostring(i)..string.rep('x',1024) end; "
            "vim.api.nvim_buf_set_lines(0,0,-1,false,lines); return true end)()")
        real_lock = p.lock
        with patch.object(p, "adapter_capture", wraps=p.adapter_capture) as capture:
            def publication_lock():
                self.assertTrue(capture.called, "application capture must precede publication lock")
                return real_lock()
            with patch.object(p, "lock", side_effect=publication_lock):
                self.save()
        _, first, _ = self.saved()
        before = stats(p.state_dir(self.a))
        audit = Changes(p.state_dir(self.a))
        self.save(rapid=True)
        self.assertEqual(audit.finish(), b"")
        self.assertEqual(stats(p.state_dir(self.a)), before)
        rpc("vim.api.nvim_buf_set_lines(0,10,11,false,{'11'..string.rep('y',1024)}) or true")
        self.save(rapid=True)
        _, second, _ = self.saved()
        old = {k: v for k, v in first["artifacts"].items() if "/objects/" in k}
        new = {k: v for k, v in second["artifacts"].items() if "/objects/" in k}
        self.assertEqual(len(set(new) - set(old)), 1)
        for name in set(old) & set(new):
            self.assertEqual(old[name], new[name])
        # Exit's submitted standalone save does not call back into this editor or
        # wait for coordinator's publication lock.
        with real_lock():
            rpc("vim.schedule(function() vim.cmd('qa!') end) or true")
            self.wait_command(self.tm, pane, "sh")
        self.assertTrue(list((Path(self.a["path"]) / ".context/state/nvim/current").glob("*/editor.json")))
        # Use only this isolated init for reconstructed editors too. RPC clients
        # bypass the shim's editor-start flags.
        binary_dir = self.base / "bin"
        binary_dir.mkdir()
        shim = binary_dir / "nvim"
        shim.write_text("#!/bin/sh\nif [ \"$1\" = --server ]; then exec " + shlex.quote(nvim) + " \"$@\"; fi\nexec "
                        + shlex.join([nvim, "--headless", "-u", str(init), "-i", "NONE", "-n"]) + " \"$@\"\n")
        shim.chmod(0o700)
        with patch.dict(os.environ, {"PATH": str(binary_dir) + os.pathsep + os.environ["PATH"]}):
            self.recover()
            restored = self.dest.rows("list-panes", ["pane_id", "@persistence-editor-socket"], "-a")
            self.assertEqual(len(restored), 1)
            contents = p.run([nvim, "--server", restored[0]["@persistence-editor-socket"], "--remote-expr",
                              'luaeval("vim.api.nvim_buf_get_lines(0,10,11,false)[1]")'])
            self.assertEqual(contents, "11" + "y" * 1024)
            self.recover()
            self.assertEqual(len(self.dest.rows("list-panes", ["pane_id"], "-a")), 1)
        self.assertFalse(list((p.local_root() / "restore").rglob("editor.json")),
                         "acknowledged restore bundles must be reclaimed")

    def test_native_capture_without_raw_backups_and_context_scoped_reconstruction(self):
        self.complex_session()
        self.session("beta private", self.b)
        self.save(context=self.a)
        base, manifest, saved = self.saved()
        raw = list((p.local_root() / "resurrect").glob("*/last"))
        self.assertEqual(raw, [], "normalized native records replace server-wide raw dumps")
        self.assertEqual([s["name"] for s in saved], ["alpha session"])
        self.assertNotIn("beta private", (base / "tmux.json").read_text())
        p.validate(base, manifest)
        self.recover()
        self.assertEqual(self.dest.call("list-sessions", "-F", "#{session_name}"), "alpha session")
        self.assertEqual(self.topology(self.captured()), self.topology(saved))

    def test_one_checkpoint_publishes_both_contexts(self):
        self.session("alpha", self.a)
        self.session("beta", self.b)
        self.align_clock()
        self.save()
        for context, name in ((self.a, "alpha"), (self.b, "beta")):
            self.assertEqual([s["name"] for s in self.saved(context)[2]], [name])

    def test_second_restore_preserves_selection_zoom_and_stable_ids(self):
        self.complex_session()
        self.save()
        self.recover()
        for pane in self.dest.rows("list-panes", ["pane_id"], "-a"):
            self.wait_command(self.dest, pane["pane_id"], "sh")
        before = self.captured()
        self.recover()
        self.assertEqual(self.topology(self.captured()), self.topology(before))

    def test_existing_live_panes_reused_missing_panes_restored_without_duplicates(self):
        first, second, third = self.complex_session()
        self.save("pre-kill")
        before = self.tm.call("display-message", "-p", "-t", first, "#{pane_pid}")
        self.tm.call("kill-pane", "-t", second)
        self.recover(tm=self.tm)
        self.assertEqual(self.tm.call("display-message", "-p", "-t", first, "#{pane_pid}"), before)
        self.assertEqual(self.topology(self.captured(self.tm)), self.topology(self.saved()[2]))
        self.recover(tm=self.tm)
        self.assertEqual(len(self.tm.rows("list-panes", ["pane_id"], "-a")), 4)

    def test_prekill_retains_absent_session_and_pane_across_periodic_save(self):
        first, second, third = self.complex_session()
        self.session("closed session", self.a)
        self.tm.call("move-window", "-s", "closed session:0", "-t", "closed session:2")
        self.save("pre-kill")
        old = self.saved()[2]
        self.tm.call("kill-session", "-t", "closed session")
        self.tm.call("kill-pane", "-t", second)
        self.save()
        saved = self.saved()[2]
        self.assertEqual({s["id"] for s in saved}, {s["id"] for s in old})
        pane_ids = lambda sessions: {q["id"] for s in sessions for w in s["windows"] for q in w["panes"]}
        self.assertEqual(pane_ids(saved), pane_ids(old))
        self.recover()
        self.assertEqual(pane_ids(self.captured()), pane_ids(old))

    def test_closed_empty_scan_preserves_latest(self):
        self.session("alpha", self.a)
        self.save("pre-kill")
        before = self.saved()[1]
        self.tm.call("kill-server")
        self.discovery.return_value = []
        self.save(context=self.a)
        self.assertEqual(self.saved()[1], before)

    def test_btop_process_restored(self):
        btop = shutil.which("btop")
        self.assertIsNotNone(btop, "btop package required for real process restoration")
        pane = self.session("monitor", self.a)
        self.tm.call("move-window", "-s", "monitor:0", "-t", "monitor:2")
        self.tm.call("send-keys", "-t", pane, btop, "Enter")
        self.wait_command(self.tm, pane, "btop")
        time.sleep(.2)
        self.assertEqual(self.tm.call("display-message", "-p", "-t", pane, "#{pane_current_command}"), "btop")
        self.save()
        self.recover()
        restored = self.dest.call("list-panes", "-a", "-F", "#{pane_id}")
        self.wait_command(self.dest, restored, "btop")

    def test_unowned_fallback_and_inferred_owner_remains_after_external_cd(self):
        external = self.base / "outside context"
        external.mkdir()
        self.session("unowned", cwd=external)
        self.tm.call("move-window", "-s", "unowned:0", "-t", "unowned:2")
        self.save()
        self.assertEqual([s["name"] for s in ctl.read_json(p.latest(None)[0] / "tmux.json")], ["unowned"])
        base, manifest = p.latest(None)
        errors = []
        p.restore_tmux(base, manifest, None, errors, self.dest)
        self.assertEqual(errors, [])
        self.assertEqual(self.dest.call("list-sessions", "-F", "#{session_name}"), "unowned")

        self.assertEqual(self.dest.call("list-panes", "-a", "-F", "#{pane_current_path}"), str(external))
        owned = self.session("inferred", cwd=self.a["path"])
        self.save(context=self.a)
        self.tm.call("send-keys", "-t", owned, "cd " + __import__("shlex").quote(str(external)), "Enter")
        deadline = time.monotonic() + 3
        while self.tm.call("display-message", "-p", "-t", owned, "#{pane_current_path}") != str(external):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        self.save(context=self.a)
        self.assertEqual([s["name"] for s in self.saved()[2]], ["inferred"])
        self.assertEqual(self.saved()[2][0]["windows"][0]["panes"][0]["cwd"],
                         {"kind": "external", "path": str(external)})

    def test_orphaned_context_is_recovered_locally_without_blocking_other_contexts(self):
        identifier = "00000000-0000-4000-8000-000000000099"
        self.session("context-" + identifier)
        self.session("owned", self.a)
        self.save()
        base, manifest = p.latest(None)
        sessions = ctl.read_json(base / "tmux.json")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["orphaned_context_id"], identifier)
        self.assertTrue(any("machine-local recovery" in warning for warning in manifest["warnings"]))
        self.assertIsNotNone(p.latest(self.a))
        self.assertEqual(len(ctl.scan()), 2, "Recovery must not recreate a deleted context")

    @staticmethod
    def align_clock():
        # Pinned plugin uses wall-clock seconds for filenames. Keep collision
        # regression reproducible without replacing date or plugin scripts.
        deadline = time.monotonic() + 2
        while time.time() % 1 > .05:
            if time.monotonic() > deadline:
                raise AssertionError("Could not align plugin timestamp test")
            time.sleep(.005)

    def test_adapter_failure_blocks_publish_and_preserves_head(self):
        self.session("alpha", self.a)
        self.save()
        before = self.saved()[1]
        for command in ("nvim", "opencode"):
            with self.subTest(adapter=command):
                original = p.capture_tmux
                def capture(*args):
                    values = original(*args)
                    values[0][2]["windows"][0]["panes"][0]["command"] = command
                    return values
                with patch.object(p, "capture_tmux", side_effect=capture):
                    with self.assertRaises(p.CheckpointError):
                        self.save("pre-kill")
                self.assertEqual(self.saved()[1], before)
                self.assertFalse((p.local_root() / f"retained-{self.a['id']}.json").exists())

    def test_latest_bad_artifact_never_falls_back(self):
        self.session("alpha", self.a)
        self.save()
        older = self.saved()[1]["id"]
        self.tm.call("rename-window", "-t", "alpha:0", "newer")
        self.save()
        base, manifest, _ = self.saved()
        self.assertNotEqual(manifest["id"], older)
        storage = p.checkpoint_store(self.a)
        artifact = storage.object(manifest["artifacts"]["tmux.json"]["chunks"][0])
        original = artifact.read_bytes()
        for damage in ("corrupt", "missing"):
            with self.subTest(damage=damage):
                artifact.write_text("corrupt")
                if damage == "missing":
                    artifact.unlink()
                base, selected = p.latest(self.a)
                self.assertEqual(selected, manifest)
                with self.assertRaisesRegex(p.CheckpointError, "missing/corrupt"):
                    p.validate(base, manifest)
                self.assertTrue(p.restore(self.a, tm=self.dest, windows=False))
                self.assertFalse(Path(self.dest.socket).exists())
                artifact.write_bytes(original)

    def test_latest_manifest_corruption_never_falls_back(self):
        self.session("alpha", self.a)
        self.save()
        self.save()
        current = p.checkpoint_store(self.a).directory / "current.json"
        current.write_text("{}")
        with self.assertRaisesRegex(p.CheckpointError, "no older fallback"):
            p.latest(self.a)
        current.unlink()
        with self.assertRaisesRegex(p.CheckpointError, "no older fallback"):
            p.latest(self.a)

    def test_schema_context_identity_and_generation_escape_rejected(self):
        self.session("alpha", self.a)
        self.save()
        base, manifest, _ = self.saved()
        current = p.checkpoint_store(self.a).directory / "current.json"
        for key, value in (("version", 999), ("context_id", self.b["id"])):
            with self.subTest(key=key):
                modified = dict(manifest, **{key: value})
                ctl.atomic_json(current, {"manifest": modified, "sha256": p.store.sha(p.store.canonical(modified))})
                with self.assertRaisesRegex(p.CheckpointError, "identity/schema"):
                    p.latest(self.a)
        for generation in ("../../outside", str(self.base)):
            modified = copy.deepcopy(manifest)
            modified["artifacts"][generation] = modified["artifacts"].pop("tmux.json")
            ctl.atomic_json(current, {"manifest": modified, "sha256": p.store.sha(p.store.canonical(modified))})
            with self.assertRaisesRegex(p.CheckpointError, "escapes"):
                p.latest(self.a)

    def test_portable_and_artifact_path_escape_rejected(self):
        for kind, path in (("context", "../escape"), ("home", "/absolute"),
                           ("unknown", "x"), ("external", "relative")):
            with self.subTest(kind=kind, path=path), self.assertRaises(p.CheckpointError):
                p.decode_path({"kind": kind, "path": path}, self.a)
        outside = self.base / "outside"
        outside.mkdir()
        base = self.base / "generation"
        base.mkdir()
        (base / "link").symlink_to(outside, target_is_directory=True)
        for path in ("../outside", str(outside), "link/file"):
            with self.subTest(path=path), self.assertRaisesRegex(p.CheckpointError, "escapes"):
                p.safe(base, path)

    def test_portable_context_path_cannot_escape_through_symlink(self):
        outside = self.base / "external"
        outside.mkdir()
        (Path(self.a["path"]) / "alias").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(p.CheckpointError):
            p.decode_path({"kind": "context", "path": "alias"}, self.a)

    def test_owner_explicit_unknown_mixed_and_machine_local(self):
        owned = {"pane_current_path": self.a["path"]}
        external = {"pane_current_path": str(self.home)}
        session = {"session_name": "ordinary", "@persistence-context": ""}
        self.assertEqual(p.owner(session, [owned], [self.a, self.b]), self.a)
        self.assertIsNone(p.owner(session, [owned, external], [self.a, self.b]))
        self.assertIsNone(p.owner(session, [external], [self.a, self.b]))
        session["@persistence-context"] = self.a["id"]
        self.assertEqual(p.owner(session, [external], [self.a, self.b]), self.a)
        session["@persistence-context"] = "unknown-context"
        with self.assertRaisesRegex(p.CheckpointError, "unknown context"):
            p.owner(session, [owned], [self.a, self.b])

    def test_bad_adapter_artifact_keeps_independent_panes_restorable(self):
        self.complex_session()
        self.save()
        base, manifest, saved = self.saved()
        pane = saved[0]["windows"][0]["panes"][0]
        relative = f"nvim/{pane['id']}/editor.json"
        pane["editor"] = {"id": "editor", "manifest": relative}
        p.write_json(base / relative, {"valid": True})
        manifest["artifacts"][relative] = {"size": len((base / relative).read_bytes()),
                                            "sha256": p.digest(base / relative)}
        p.write_json(base / "tmux.json", saved)
        manifest["artifacts"]["tmux.json"] = {"size": len((base / "tmux.json").read_bytes()),
                                               "sha256": p.digest(base / "tmux.json")}
        del base.tree.files[relative]
        errors = []
        mapping = p.restore_tmux(base, manifest, self.a, errors, self.dest)
        self.assertEqual(set(mapping), {saved[0]["id"]}, errors)
        self.assertTrue(any("missing/corrupt" in error for error in errors), errors)
        panes = self.dest.rows("list-panes", ["pane_id", "@persistence-id", "pane_current_command"], "-a")
        expected = {q["id"] for w in saved[0]["windows"] for q in w["panes"]}
        self.assertEqual({q["@persistence-id"] for q in panes}, expected)
        for row in panes:
            self.wait_command(self.dest, row["pane_id"], "sh")
        panes = self.dest.rows("list-panes", ["@persistence-id", "pane_current_command"], "-a")
        self.assertTrue(all(q["pane_current_command"] in ("sh", "bash") for q in panes))

    def test_failed_program_placeholder_cannot_replace_saved_recovery_on_next_scan(self):
        self.session("failed chat", self.a)
        self.session("independent healthy", self.a)
        original = p.adapter_capture
        injected = []

        def capture(tm, pane, destination, context, errors):
            original(tm, pane, destination, context, errors)
            if not injected:
                injected.append(pane["id"])
                pane["chat"] = f"opencode/{pane['id']}"
                p.chats.capture({"session_id": None, "directory": context["cwd"]},
                                destination / pane["chat"], context["cwd"])

        with patch.object(p, "adapter_capture", side_effect=capture):
            self.save()
        before = self.saved()[1]["id"]
        with patch.object(p.chats, "restore", side_effect=RuntimeError("native import unavailable")):
            p.restore(self.a, tm=self.dest, windows=False)
        pending = [row for row in self.dest.rows("list-panes", ["pane_id", "pane_pid", "@persistence-recovery-pending"], "-a")
                   if row["@persistence-recovery-pending"] == "1"]
        self.assertEqual(len(pending), 1)
        self.discovery.return_value = [self.dest]
        with self.assertRaises(p.CheckpointError):
            self.save()
        self.assertEqual(self.saved()[1]["id"], before)
        self.assertEqual(len(self.dest.rows("list-sessions", ["session_id"])), 2)
        with patch.object(p.chats, "restore") as retry:
            p.restore(self.a, tm=self.dest, windows=False)
        retry.assert_not_called()
        self.assertEqual(len(self.dest.rows("list-panes", ["pane_id"], "-a")), 2)
        self.assertEqual(self.dest.call("display-message", "-p", "-t", pending[0]["pane_id"], "#{pane_pid}"), pending[0]["pane_pid"])
        self.assertTrue(ctl.read_json(p.local_root() / f"retained-{self.a['id']}.json")["sessions"])

    def test_desktop_restore_reuses_windows_and_restores_placement_without_spawning(self):
        window = {"id": "terminal-id", "session": "session-id", "order": 0, "monitor": "DP-1",
                  "workspace": {"slot": 4, "role": None}, "floating": True,
                  "geometry": [.1, .2, .5, .6], "focused": True, "fullscreen": 0,
                  "fullscreen_client": 0}
        desktop = {"windows": [window], "desktop": [{"monitor": "DP-1", "slot": 4}]}
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), \
                patch.object(p, "run", return_value=json.dumps([{"name": "DP-1"}])), \
                patch.object(ctl, "clients", return_value=[{"class": "context-terminal-terminal-id",
                                                            "address": "0xabc", "pid": 123}]), \
                patch.object(ctl, "spawn") as spawn, patch.object(ctl, "evaluate") as evaluate:
            errors = []
            p.restore_windows(desktop, {"session-id": {"socket": self.dest.socket, "target": "$0"}},
                              self.a, "runtime-test", errors)
        self.assertEqual(errors, [])
        spawn.assert_not_called()
        calls = [call.args[0] for call in evaluate.call_args_list]
        self.assertIn(".place(", calls[0])
        self.assertIn('[' + ctl.lua_string("slot") + ']=4', calls[0])
        self.assertIn('[' + ctl.lua_string("geometry") + ']={0.1,0.2,0.5,0.6}', calls[0])
        self.assertIn(".view(", calls[1])
        self.assertIn(ctl.lua_string("address:0xabc"), calls[2])

    def test_inventory_uses_context_workspace_and_normalizes_geometry(self):
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}):
            ctl.save_state({"mappings": {self.a["id"]: "runtime-test"}, "last_active": None})
        window = {"class": "context-terminal-logical-id", "address": "0x123", "pid": 99999999,
                  "workspace": {"name": "special:session-runtime-test-notes"}, "monitor": 1,
                  "at": [1100, 100], "size": [500, 400], "floating": True}
        monitor = {"id": 1, "name": "DP-1", "width": 2000, "height": 1000, "scale": 2,
                   "x": 1000, "y": 0, "activeWorkspace": {"name": "session-runtime-test-abcd-4"},
                   "specialWorkspace": {"name": "special:session-runtime-test-notes"}}
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), \
                patch.object(ctl, "clients", return_value=[window]), \
                patch.object(p, "run", side_effect=[json.dumps([monitor]), json.dumps({"address": "0x123"})]):
            result = p.inventory(self.a, [])
        saved = result["windows"][0]
        self.assertEqual(saved["id"], "logical-id")
        self.assertEqual(saved["workspace"], {"role": "notes", "slot": 1})
        self.assertEqual(saved["geometry"], [.1, .2, .5, .8])
        self.assertTrue(saved["focused"])
        self.assertTrue(result["warnings"])
        # Portable desktop selection must retain logical slot/role, not runtime workspace names.
        self.assertEqual(result["desktop"][0].get("slot"), 4)
        self.assertEqual(result["desktop"][0].get("role"), "notes")

    def test_inactive_context_uses_remembered_view_and_terminal_mru(self):
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}):
            ctl.save_state({"mappings": {self.a["id"]: "runtime-test"}, "last_active": None})
        windows = [{"class": "kitty", "address": f"0x{index}", "pid": 99999990 + index,
                    "workspace": {"name": "session-runtime-test-abcd-4"}, "monitor": 1,
                    "focusHistoryID": rank, "at": [0, 0], "size": [500, 400], "floating": True}
                   for index, rank in ((1, 7), (2, 2))]
        monitor = {"id": 1, "name": "DP-1", "width": 2000, "height": 1000, "scale": 1,
                   "activeWorkspace": {"name": "session-unrelated-abcd-9"},
                   "specialWorkspace": {"name": "special:session-unrelated-notes"}}
        remembered = {"id": "runtime-test", "name": "test", "slots": {"DP-1": 4},
                      "visible_specials": {"DP-1": "terminal"}}
        with patch.dict(os.environ, {"HYPRLAND_INSTANCE_SIGNATURE": "test"}), \
                patch.object(ctl, "snapshot", return_value={"sessions": [remembered]}), \
                patch.object(ctl, "clients", return_value=windows), \
                patch.object(p, "run", side_effect=[json.dumps([monitor]), json.dumps({"address": "0xother"})]):
            result = p.inventory(self.a, [])
        self.assertEqual(result["desktop"], [{"monitor": "DP-1", "slot": 4, "role": "terminal"}])
        self.assertEqual([window["focused"] for window in result["windows"]], [False, True])

    def test_external_root_mapping_applies_to_descendant_working_directories(self):
        ctl.atomic_json(p.local_root() / "external-roots.json", {"/old/root": "/new/root"})
        self.assertEqual(p.decode_path({"kind": "external", "path": "/old/root/sub project"}, self.a),
                         Path("/new/root/sub project"))

    def test_chat_reconstruction_uses_selected_ui_directory(self):
        directory = Path(self.a["path"]) / "selected project"
        directory.mkdir()
        pane = {"id": "pane", "command": "opencode", "cwd": p.encode_path(self.a["path"], self.a),
                "chat_cwd": p.encode_path(directory, self.a), "chat": "opencode/pane"}
        errors = []
        with patch.object(p.chats, "restore", return_value="ses_exact") as restore:
            command = p.pane_command(pane, self.base, self.a, errors)
        self.assertEqual(errors, [])
        self.assertEqual(command[:3], ["env", "-C", str(directory)])
        self.assertEqual(command[-3:], ["opencode", "--session", "ses_exact"])
        self.assertEqual(restore.call_args.args[1], str(directory))

    def test_retained_deleted_pane_plus_new_pane_has_coherent_three_pane_layout(self):
        first = self.session("retained", self.a)
        removed = self.tm.call("split-window", "-d", "-h", "-P", "-F", "#{pane_id}",
                               "-t", first, "-c", self.a["path"], "/bin/sh")
        self.wait_command(self.tm, removed, "sh")
        self.save("pre-kill")
        original = self.saved()[2][0]["windows"][0]
        self.tm.call("kill-pane", "-t", removed)
        added = self.tm.call("split-window", "-d", "-v", "-P", "-F", "#{pane_id}",
                             "-t", first, "-c", self.a["path"], "/bin/sh")
        self.wait_command(self.tm, added, "sh")
        added_id = self.tm.identity(added, ["-p"])
        self.save()
        base, manifest, saved = self.saved()
        window = saved[0]["windows"][0]
        self.assertEqual(len(window["panes"]), 3)
        self.assertEqual({q["id"] for q in window["panes"]},
                         {q["id"] for q in original["panes"]} | {added_id})
        self.assertEqual(sorted(q["index"] for q in window["panes"]), [0, 1, 2])
        leaves = re.findall(r"\d+x\d+,\d+,\d+,(\d+)(?=[,}\]]|$)", window["layout"])
        self.assertEqual(len(leaves), 3)
        self.assertEqual(set(leaves), {q["observed_id"].lstrip("%") for q in window["panes"]})
        p.validate(base, manifest)
        self.recover()
        self.assertEqual(self.topology(self.captured()), self.topology(saved))
        self.recover()
        self.assertEqual(len(self.dest.rows("list-panes", ["pane_id"], "-a")), 3)

    def shared_adapter_capture(self, grouped):
        first = self.session("primary", self.a)
        second = self.tm.call("split-window", "-d", "-P", "-F", "#{pane_id}",
                              "-t", first, "-c", self.a["path"], "/bin/sh")
        self.wait_command(self.tm, second, "sh")
        if grouped:
            self.tm.call("new-session", "-d", "-t", "primary", "-s", "shared")
            self.tm.call("set-option", "-t", "shared", "@persistence-context", self.a["id"])
        else:
            self.session("shared", self.a)
            self.tm.call("link-window", "-s", "primary:0", "-t", "shared:3")
        physical = {q["pane_id"] for q in self.tm.rows("list-panes", ["pane_id"], "-a")}
        with patch.object(p, "adapter_capture", wraps=p.adapter_capture) as adapter:
            self.save()
        calls = [(call.args[0].socket, call.args[1]["id"]) for call in adapter.call_args_list]
        self.assertEqual(len(calls), len(physical), "adapter must run once per physical pane")
        self.assertEqual(len(set(calls)), len(physical))
        saved = self.saved()[2]
        self.assertEqual({s["name"] for s in saved}, {"primary", "shared"})
        panes = [q for s in saved for w in s["windows"] for q in w["panes"]]
        self.assertGreater(len(panes), len(physical), "fixture must really share physical panes")
        self.assertTrue(all("local" not in q for q in panes))

    def test_grouped_physical_panes_capture_adapters_once(self):
        self.shared_adapter_capture(grouped=True)

    def test_linked_physical_panes_capture_adapters_once(self):
        self.shared_adapter_capture(grouped=False)

    def test_retained_desktop_session_survives_other_live_terminal_inventory(self):
        self.session("closed terminal", self.a)
        self.session("live terminal", self.a)
        sessions = {s["name"]: s for s in self.captured(self.tm)}
        def window(name, logical, order):
            return {"id": logical, "session": sessions[name]["id"], "order": order,
                    "monitor": "DP-test", "workspace": {"slot": order + 1, "role": None},
                    "floating": True, "geometry": [.1, .2, .3, .4], "fullscreen": 0,
                    "fullscreen_client": 0, "focused": order == 0}
        closed = window("closed terminal", "closed-client", 0)
        live = window("live terminal", "live-client", 1)
        # Mock compositor inventory only; session disappearance and retention are real.
        with patch.object(p, "inventory", return_value={"windows": [closed, live],
                                                       "desktop": [], "warnings": []}):
            self.save("pre-kill")
        self.tm.call("kill-session", "-t", "closed terminal")
        live_changed = copy.deepcopy(live)
        live_changed["geometry"] = [.4, .3, .2, .1]
        with patch.object(p, "inventory", return_value={"windows": [live_changed],
                                                       "desktop": [], "warnings": []}):
            self.save()
        desktop = ctl.read_json(self.saved()[0] / "desktop.json")
        self.assertEqual({w["id"] for w in desktop["windows"]}, {"closed-client", "live-client"})
        by_id = {w["id"]: w for w in desktop["windows"]}
        self.assertEqual(by_id["closed-client"], closed)
        self.assertEqual(by_id["live-client"], live_changed)
        self.recover()
        self.assertEqual({s["name"] for s in self.captured()}, {"closed terminal", "live terminal"})

    def test_partial_failed_restore_remains_retained_after_next_checkpoint(self):
        self.complex_session()
        self.save()
        original = self.saved()[2]
        real_call = self.dest.call
        def fail_window(*args):
            if args[0] == "new-window":
                raise p.CheckpointError("injected native new-window failure")
            return real_call(*args)
        with patch.object(self.dest, "call", side_effect=fail_window):
            self.assertTrue(p.restore(self.a, tm=self.dest, windows=False))
        retained_path = p.local_root() / f"retained-{self.a['id']}.json"
        self.assertIn(original[0]["id"], ctl.read_json(retained_path)["sessions"])
        self.assertIn("injected native new-window failure", str(self.notices.call_args_list))
        self.assertEqual(len(self.dest.rows("list-windows", ["window_id"], "-a")), 1)
        self.tm.call("kill-server")
        self.discovery.return_value = [self.dest]
        self.save(context=self.a)
        saved = self.saved()[2]
        self.assertEqual(self.topology(saved), self.topology(original))
        self.assertTrue(p.restore(self.a, tm=self.dest, windows=False))
        self.assertEqual(ctl.read_json(retained_path)["sessions"], [])
        self.assertEqual(self.topology(self.captured()), self.topology(original))
        self.assertTrue(p.restore(self.a, tm=self.dest, windows=False))
        self.assertEqual(len(self.dest.rows("list-panes", ["pane_id"], "-a")), 4)

    def test_same_session_name_on_alternate_sockets_restores_by_server_identity(self):
        alternate = self.new_server("alternate-source")
        target = self.new_server("alternate-target")
        paths = [Path(self.a["path"]) / name for name in ("first socket cwd", "second socket cwd")]
        for tm, path in zip((self.tm, alternate), paths):
            path.mkdir()
            self.session("same name", self.a, cwd=path, tm=tm)
        self.discovery.return_value = [self.tm, alternate]
        self.save()
        base, manifest, saved = self.saved()
        self.assertEqual(len(saved), 2)
        self.assertEqual(len({s["server"]["id"] for s in saved}), 2)
        self.assertEqual(len({s["id"] for s in saved}), 2)
        for session, tm in zip(saved, (self.dest, target)):
            for attempt in range(2):
                with self.subTest(server=session["server"]["id"], attempt=attempt):
                    errors = []
                    mapping = p.restore_tmux(base, manifest, self.a, errors, tm,
                                             server_id=session["server"]["id"])
                    self.assertEqual(errors, [])
                    self.assertEqual(set(mapping), {session["id"]})
                    self.assertEqual(tm.call("list-sessions", "-F", "#{session_name}"), "same name")
                    self.assertEqual(self.topology(self.captured(tm)), self.topology([session]))

    def test_closed_lifecycle_preserves_head_then_open_restore_reuses_live_panes(self):
        first = self.session("lifecycle", self.a)
        self.save("close")
        head = self.saved()[1]
        p.set_lifecycle(self.a, "closed")
        second = self.tm.call("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", first,
                              "-c", self.a["path"], "/bin/sh")
        self.wait_command(self.tm, second, "sh")
        for reason in ("periodic", "shutdown"):
            self.save(reason)
            self.assertEqual(self.saved()[1], head)
        p.set_lifecycle(self.a, "open")
        before = self.tm.call("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
        for attempt in range(2):
            self.assertTrue(p.restore(self.a, tm=self.tm, windows=False))
            self.assertEqual(self.tm.call("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}"), before)
        self.save()
        self.assertNotEqual(self.saved()[1]["id"], head["id"])
        self.assertEqual(len(self.saved()[2][0]["windows"][0]["panes"]), 2)

    def require_native_operation_formats(self):
        # Prior native patch has barrier support but not resolved operation flags.
        # Do not silently run a reduced integration contract against that binary.
        binary = Path(shutil.which(TMUX)).read_bytes()
        required = (b"checkpoint_operation", b"checkpoint_all", b"checkpoint_group")
        if not all(name in binary for name in required):
            self.skipTest("final native build required: checkpoint_operation/checkpoint_all/checkpoint_group absent")

    def test_resolved_operation_flags_checkpoint_only_affected_context(self):
        nvim = shutil.which("nvim")
        self.assertIsNotNone(nvim, "real failing unrelated editor adapter requires nvim")
        first = self.session("affected", self.a)
        unrelated = self.session("unrelated", self.b)
        self.tm.call("send-keys", "-t", unrelated,
                     shlex.join([nvim, "--clean", "-i", "NONE"]), "Enter")
        self.wait_command(self.tm, unrelated, "nvim")
        self.tm.call("new-window", "-d", "-t", "affected:1", "-c", self.a["path"], "/bin/sh")
        self.tm.call("new-session", "-d", "-t", "affected", "-s", "affected grouped")
        self.tm.call("set-option", "-t", "affected grouped", "@persistence-context", self.a["id"])
        target = self.tm.call("display-message", "-p", "-t", first, "#{session_id} #{window_id}").split()
        excluded = self.tm.call("display-message", "-p", "-t", unrelated, "#{session_id} #{window_id}").split()
        for operation, all_targets, group in (("kill-session", False, False),
                                              ("kill-session", True, False),
                                              ("kill-session", False, True),
                                              ("kill-window", False, False),
                                              ("kill-window", True, False),
                                              ("kill-pane", False, False),
                                              ("kill-pane", True, False)):
            with self.subTest(operation=operation, all_targets=all_targets, group=group):
                session_id, window_id = excluded if operation == "kill-session" and all_targets else target
                p.checkpoint("pre-kill", socket_path=self.tm.socket, operation=operation,
                             target_session=session_id, target_window=window_id,
                             all_targets=all_targets, group=group)
                base, manifest, _ = self.saved()
                self.assertEqual(manifest["reason"], "pre-kill")
                p.validate(base, manifest)
                self.assertIsNone(p.latest(self.b), "unrelated editor adapter must never block or publish")

    def native_coordinator_barrier(self, operation, flag=None):
        self.require_native_operation_formats()
        nvim = shutil.which("nvim")
        self.assertIsNotNone(nvim, "real failing unrelated editor adapter requires nvim")
        first = self.session("victim", self.a)
        unrelated = self.session("unrelated failing adapter", self.b)
        self.tm.call("send-keys", "-t", unrelated,
                     shlex.join([nvim, "--clean", "-i", "NONE"]), "Enter")
        self.wait_command(self.tm, unrelated, "nvim")
        if flag == "-g":
            self.tm.call("new-session", "-d", "-t", "victim", "-s", "victim grouped")
            self.tm.call("set-option", "-t", "victim grouped", "@persistence-context", self.a["id"])
        if operation == "kill-window":
            extra_window = self.tm.call("new-window", "-d", "-P", "-F", "#{pane_id}", "-t", "victim:1",
                                        "-c", self.a["path"], "/bin/sh")
            self.wait_command(self.tm, extra_window, "sh")
        if operation == "kill-pane":
            extra = self.tm.call("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", first,
                                 "-c", self.a["path"], "/bin/sh")
            self.wait_command(self.tm, extra, "sh")
        # Verify unrelated context genuinely cannot checkpoint, without publishing it.
        with self.assertRaises(p.CheckpointError):
            self.save(context=self.b)
        self.assertIsNone(p.latest(self.b))
        source = str(Path(p.__file__).parent)
        # Invoke actual CLI/coordinator in another process. Restrict discovery to
        # this socket even there; production discovery would scan user servers.
        code = ("import sys;sys.path.insert(0," + repr(source) + ");import persistence as p;"
                "p.sockets=lambda extra=None:[p.Tmux(" + repr(self.tm.socket) + ")];"
                "p.notify=lambda errors:p.report('; '.join(errors)) if errors else None;"
                "sys.exit(p.main())")
        command = shlex.join([sys.executable, "-B", "-c", code, "pre-kill", "--socket", self.tm.socket])
        command += (' --operation #{checkpoint_operation} --target-session #{q:session_id}'
                    ' --target-window #{q:window_id} --all #{checkpoint_all} --group #{checkpoint_group}')
        self.tm.call("set-option", "-s", "@persistence-checkpoint", command)
        if operation == "kill-session":
            target_name = "unrelated failing adapter" if flag == "-a" else "victim"
        elif operation == "kill-window":
            target_name = "victim:0" if flag == "-a" else "victim:1"
        else:
            target_name = first if flag == "-a" else extra
        result = subprocess.run([TMUX, "-S", self.tm.socket, operation,
                                 *([flag] if flag else []), "-t", target_name],
                                capture_output=True, text=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr)
        base, manifest, saved = self.saved()
        self.assertEqual(manifest["reason"], "pre-kill")
        p.validate(base, manifest)
        self.assertIsNone(p.latest(self.b), "unrelated failing adapter must not be checkpointed")
        self.assertEqual(self.tm.call("display-message", "-p", "-t", unrelated,
                                      "#{pane_current_command}"), "nvim")
        names = self.tm.call("list-sessions", "-F", "#{session_name}").splitlines()
        if operation == "kill-session":
            self.assertEqual(names, ["unrelated failing adapter"])
            self.assertEqual({s["name"] for s in saved},
                             {"victim", "victim grouped"} if flag == "-g" else {"victim"})
        elif operation == "kill-window":
            self.assertEqual(len(saved[0]["windows"]), 2, "capture must precede window deletion")
            self.assertEqual(self.tm.call("list-windows", "-t", "victim", "-F", "#{window_index}"), "0")
        else:
            self.assertEqual(len(saved[0]["windows"][0]["panes"]), 2, "capture must precede pane deletion")
            self.assertEqual(self.tm.call("list-panes", "-t", "victim", "-F", "#{pane_id}"), first)

    def test_native_coordinator_barrier_kill_session(self):
        self.native_coordinator_barrier("kill-session")

    def test_native_coordinator_barrier_kill_window(self):
        self.native_coordinator_barrier("kill-window")

    def test_native_coordinator_barrier_kill_pane(self):
        self.native_coordinator_barrier("kill-pane")

    def test_native_coordinator_barrier_kill_session_all_excludes_target_context(self):
        self.native_coordinator_barrier("kill-session", "-a")

    def test_native_coordinator_barrier_kill_session_group(self):
        self.native_coordinator_barrier("kill-session", "-g")

    def test_native_coordinator_barrier_kill_window_all(self):
        self.native_coordinator_barrier("kill-window", "-a")

    def test_native_coordinator_barrier_kill_pane_all(self):
        self.native_coordinator_barrier("kill-pane", "-a")


if __name__ == "__main__":
    unittest.main()
