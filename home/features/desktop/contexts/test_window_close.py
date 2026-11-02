"""Tab-close semantics on isolated servers; never touch desktop/user sockets."""

import json
import os
from pathlib import Path
import pty
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import contextctl as ctl
import persistence as p
import window_close as close


TMUX = os.environ.get("PERSISTENCE_TMUX") or shutil.which("tmux")


@unittest.skipUnless(TMUX and os.environ.get("PERSISTENCE_NATIVE_TESTS") == "1", "isolated native tests opt-in")
class WindowCloseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tab-close-", dir="/tmp/opencode")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "home").mkdir()
        self.enterContext(patch.dict(os.environ, {
            "HOME": str(self.root / "home"), "CONTEXT_ROOT": str(self.root / "contexts"),
            "XDG_STATE_HOME": str(self.root / "state"), "XDG_RUNTIME_DIR": str(self.root / "runtime"),
            "XDG_CONFIG_HOME": str(self.root / "config"), "XDG_DATA_HOME": str(self.root / "data"),
            "HYPRLAND_INSTANCE_SIGNATURE": "", "PERSISTENCE_TMUX": TMUX, "TMUX": "", "SHELL": "/bin/sh"}))
        self.context = ctl.find_context(ctl.create("Working context")["id"])
        self.other = ctl.find_context(ctl.create("Other context")["id"])
        self.tm = p.Tmux(self.root / "source.sock")
        self.dest = p.Tmux(self.root / "restore.sock")
        self.addCleanup(self.cleanup_servers)
        self.tm.call("-f", "/dev/null", "new-session", "-d", "-s", "work", "-c", self.context["path"], "/bin/sh")
        self.tm.call("set-option", "-g", "default-shell", "/bin/sh")
        self.tm.call("set-option", "-t", "work", "@persistence-context", self.context["id"])
        self.tm.call("new-session", "-d", "-s", "unrelated", "-c", self.other["path"], "/bin/sh")
        self.tm.call("set-option", "-t", "unrelated", "@persistence-context", self.other["id"])
        self.pane = self.tm.call("new-window", "-d", "-P", "-F", "#{pane_id}", "-t", "work:", "/bin/sh")
        self.window = self.tm.call("display-message", "-p", "-t", self.pane, "#{window_id}")
        self.session = self.tm.call("display-message", "-p", "-t", self.pane, "#{session_id}")
        self.enterContext(patch.object(p, "sockets", return_value=[self.tm]))
        self.notices = self.enterContext(patch.object(p, "notify"))
        p.checkpoint("manual", socket_path=self.tm.socket)

    def cleanup_servers(self):
        for tm in (self.tm, self.dest):
            subprocess.run([TMUX, "-S", tm.socket, "set-option", "-su", "@persistence-close-command"], capture_output=True)
            subprocess.run([TMUX, "-S", tm.socket, "set-option", "-su", "@persistence-checkpoint"], capture_output=True)
            subprocess.run([TMUX, "-S", tm.socket, "kill-server"], capture_output=True)

    def close(self, operation="kill-window", pane=None, all_targets=False):
        close.close_tab(self.tm.socket, operation, self.session, self.window, pane or self.pane, all_targets)

    def restore(self):
        base, manifest = p.latest(self.context)
        errors = []
        p.restore_tmux(base, manifest, self.context, errors, self.dest)
        self.assertEqual(errors, [])
        return self.dest.rows("list-panes", ["@persistence-id"], "-a")

    def test_shell_close_forgets_stale_snapshot_without_export_or_other_session_calls(self):
        identity = self.tm.identity(self.pane, ("-p",))
        other_before = p.latest(self.other)[1]
        original = self.tm.call
        calls = []

        def call(*args):
            calls.append(args)
            return original(*args)

        with patch.object(p.Tmux, "call", side_effect=call), \
                patch.object(ctl, "scan", side_effect=AssertionError("no unrelated context scan")), \
                patch.object(p, "adapter_capture", side_effect=AssertionError("shell close must not export")), \
                patch.object(p.chat_library, "sync_all", side_effect=AssertionError("no library sweep")), \
                patch.object(p, "checkpoint", side_effect=AssertionError("no checkpoint")):
            self.close()
        self.assertTrue(all("-a" not in args for args in calls), calls)
        self.assertTrue(all("unrelated" not in str(args) for args in calls))
        self.assertEqual(p.latest(self.other)[1], other_before)
        self.assertNotIn(identity, {r["@persistence-id"] for r in self.restore()})
        # Portable deletion still applies when the local journal is absent.
        shutil.rmtree(close.record_roots(self.context)[0])
        self.assertIn(identity, close.closed_ids(self.context))

    def test_close_renumbers_remaining_windows_only_when_enabled(self):
        for enabled in (False, True):
            with self.subTest(renumber=enabled):
                self.tm.call("set-option", "-t", "work", "base-index", "1")
                self.tm.call("set-option", "-t", "work", "renumber-windows", "on" if enabled else "off")
                self.tm.call("move-window", "-r", "-t", "work")
                tail = self.tm.call("new-window", "-d", "-P", "-F", "#{window_id}", "-t", "work:", "/bin/sh")
                self.close()
                windows = self.tm.rows("list-windows", ["window_id", "window_index"], "-t", "work")
                self.assertEqual([r["window_index"] for r in windows], ["1", "2" if enabled else "3"])
                self.assertEqual(windows[-1]["window_id"], tail)
                # Reuse the trailing window as the next close target.
                self.window = tail
                self.pane = self.tm.call("display-message", "-p", "-t", tail, "#{pane_id}")

    def test_legacy_retained_window_does_not_resurrect_after_later_checkpoint(self):
        identity = self.tm.identity(self.pane, ("-p",))
        p.checkpoint("pre-kill", socket_path=self.tm.socket)
        self.close()
        p.checkpoint("manual", socket_path=self.tm.socket)
        saved = ctl.read_json(p.latest(self.context)[0] / "tmux.json")
        self.assertNotIn(identity, {pane["id"] for s in saved for w in s["windows"] for pane in w["panes"]})

    def test_single_pane_close_prunes_stale_layout_and_restores_remaining_pane(self):
        second = self.tm.call("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", self.pane, "/bin/sh")
        p.checkpoint("manual", socket_path=self.tm.socket)
        identity = self.tm.identity(self.pane, ("-p",))
        survivor = self.tm.identity(second, ("-p",))
        self.close("kill-pane")
        identities = {r["@persistence-id"] for r in self.restore()}
        self.assertNotIn(identity, identities)
        self.assertIn(survivor, identities)

    def test_closing_final_pane_forgets_final_tab(self):
        original = self.tm.call("display-message", "-p", "-t", "work:0", "#{pane_id}")
        self.tm.call("kill-pane", "-t", original)
        p.checkpoint("manual", socket_path=self.tm.socket)
        self.close("kill-pane")
        base, manifest = p.latest(self.context)
        errors = []
        self.assertEqual(p.restore_tmux(base, manifest, self.context, errors, self.dest), {})
        self.assertEqual(errors, [])

    def test_slow_capture_hides_window_before_rpc_and_keeps_process_alive_on_failure(self):
        self.tm.call("set-option", "-t", "work", "renumber-windows", "on")
        self.tm.call("new-window", "-d", "-t", "work:", "/bin/sh")
        self.tm.call("set-option", "-p", "-t", self.pane, "@persistence-chat-socket", "/fixture/chat.sock")
        started, release = threading.Event(), threading.Event()
        errors = []

        def capture(*_args):
            started.set()
            self.assertTrue(release.wait(5))
            raise p.CheckpointError("fixture capture failed")

        def worker():
            try:
                self.close()
            except Exception as exc:
                errors.append(exc)

        with patch.object(p, "adapter_capture", side_effect=capture):
            thread = threading.Thread(target=worker)
            thread.start()
            try:
                self.assertTrue(started.wait(5))
                self.assertNotIn(self.window, self.tm.call("list-windows", "-t", "work", "-F", "#{window_id}").splitlines())
                self.assertEqual(self.tm.call("list-windows", "-t", "work", "-F", "#{window_index}").splitlines(), ["0", "1"])
                self.assertIn(close.STAGING, self.tm.call("display-message", "-p", "-t", self.pane, "#{session_name}"))
                self.tm.call("select-window", "-t", "work:0")
                self.tm.call("new-window", "-d", "-t", "work:", "/bin/sh")
                self.assertTrue(thread.is_alive())
            finally:
                release.set()
                thread.join(5)
        self.assertEqual(len(errors), 1)
        self.assertTrue(self.tm.call("display-message", "-p", "-t", self.pane, "#{pane_pid}"))
        status = list((p.local_root() / "closed-work").glob("*/status.json"))
        self.assertEqual(ctl.read_json(status[0])["status"], "failed")
        with patch.object(p, "adapter_capture"):
            close.retry_close(status[0].parent.name)
        self.assertEqual(ctl.read_json(status[0])["status"], "saved")

    def test_offline_unrelated_working_directory_is_never_probed(self):
        metadata = Path(self.other["path"]) / ".context/context.json"
        value = ctl.read_json(metadata)
        value["working_directory"] = "/mnt/fixture-offline"
        ctl.atomic_json(metadata, value)
        original = Path.is_dir

        def is_dir(path):
            if str(path).startswith("/mnt/fixture-offline"):
                raise AssertionError("unrelated network path was probed")
            return original(path)

        with patch.object(Path, "is_dir", is_dir):
            self.close()

    def test_linked_window_close_removes_all_links_without_archiving_other_context(self):
        self.tm.call("set-option", "-g", "renumber-windows", "on")
        self.tm.call("link-window", "-s", self.window, "-t", "unrelated:3")
        self.tm.call("new-window", "-d", "-t", "unrelated:5", "/bin/sh")
        p.checkpoint("manual", socket_path=self.tm.socket)
        before = p.latest(self.other)[1]
        identity = self.tm.identity(self.pane, ("-p",))
        self.close()
        self.assertNotIn(self.window, self.tm.call("list-windows", "-t", "unrelated", "-F", "#{window_id}").splitlines())
        self.assertEqual(self.tm.call("list-windows", "-t", "unrelated", "-F", "#{window_index}").splitlines(), ["0", "1"])
        self.assertEqual(p.latest(self.other)[1], before)
        self.assertNotIn(identity, {r["@persistence-id"] for r in self.restore()})
        saved_other = ctl.read_json(p.latest(self.other)[0] / "tmux.json")
        self.assertNotIn(identity, {pane["id"] for s in close.filter_closed(saved_other, self.other)
                                  for w in s["windows"] for pane in w["panes"]})

    def test_session_archive_only_captures_selected_session_and_restores_it(self):
        captured = []
        original = p.adapter_capture

        def adapter(tm, pane, *args):
            captured.append(tm.call("display-message", "-p", "-t", pane["local"]["pane_id"], "#{session_name}"))
            return original(tm, pane, *args)

        with patch.object(p, "adapter_capture", side_effect=adapter):
            p.checkpoint("pre-kill", socket_path=self.tm.socket, operation="kill-session", target_session=self.session)
        self.assertEqual(set(captured), {"work"})
        self.tm.call("kill-session", "-t", "work")
        self.assertEqual(len(self.restore()), 2)

    def test_targeted_archive_preserves_other_saved_sessions_in_same_context(self):
        self.tm.call("new-session", "-d", "-s", "sibling", "-c", self.context["path"], "/bin/sh")
        self.tm.call("set-option", "-t", "sibling", "@persistence-context", self.context["id"])
        p.checkpoint("manual", socket_path=self.tm.socket)
        p.checkpoint("pre-kill", socket_path=self.tm.socket, operation="kill-session", target_session=self.session)
        saved = ctl.read_json(p.latest(self.context)[0] / "tmux.json")
        self.assertEqual({s["name"] for s in saved}, {"work", "sibling"})

    def test_native_dispatch_runs_real_tab_worker_without_waiting_for_capture(self):
        # A fake editor socket routes only this pane through the capture adapter.
        # The shell command remains sh; chat socket forces adapter selection and
        # a fixture adapter supplies recoverable bytes after a held wait.
        code = ("import persistence as p,time; "
                "p.adapter_capture=lambda tm,pane,dest,ctx,warnings: "
                "(time.sleep(1), (dest/'unsaved.txt').write_bytes(b'unsaved work')); "
                "raise SystemExit(p.main())")
        self.tm.call("set-option", "-p", "-t", self.pane, "@persistence-chat-socket", "/fixture/chat.sock")
        command = shlex.join([sys.executable, "-B", "-c", code, "close-tab", "--socket", self.tm.socket])
        command += " --operation #{checkpoint_operation} --target-session x#{q:session_id} --target-window x#{q:window_id} --target-pane x#{q:pane_id} --all #{checkpoint_all}"
        # job cwd is /; supply module lookup without relying on test cwd.
        command = "env PYTHONPATH=" + shlex.quote(str(Path(p.__file__).parent)) + " " + command
        self.tm.call("set-option", "-s", "@persistence-close-command", command)
        before = time.monotonic()
        self.tm.call("kill-window", "-t", self.window)
        self.assertLess(time.monotonic() - before, .5, "native close command waited for exporter")
        deadline = time.monotonic() + 4
        while self.window in self.tm.call("list-windows", "-t", "work", "-F", "#{window_id}").splitlines():
            self.assertLess(time.monotonic(), deadline, "closing tab never hidden")
            time.sleep(.01)
        hidden_after = time.monotonic() - before
        self.assertLess(hidden_after, .5, "tab hiding waited for exporter")
        self.assertIn(close.STAGING, self.tm.call("display-message", "-p", "-t", self.pane, "#{session_name}"))
        statuses = []
        while not statuses:
            self.assertLess(time.monotonic(), deadline, "background capture never completed")
            statuses = list((p.local_root() / "closed-work").glob("*/status.json"))
            time.sleep(.01)
        self.assertEqual(ctl.read_json(statuses[0])["status"], "saved")
        self.assertEqual(list((p.local_root() / "closed-work").glob("*/*/unsaved.txt"))[0].read_bytes(), b"unsaved work")
        while close.STAGING in self.tm.call("list-sessions", "-F", "#{session_name}"):
            self.assertLess(time.monotonic(), deadline, "staging process teardown never completed")
            time.sleep(.01)
        print(f"tab-close fixture: hidden in {hidden_after * 1000:.1f}ms; exporter held 1000ms")

    def test_running_server_background_binding_keeps_originating_client_interactive(self):
        helper = self.root / "context-checkpoint"
        helper.write_text(f"#!{sys.executable}\nimport sys,time,json\nopen({str(self.root / 'worker-argv.json')!r},'w').write(json.dumps(sys.argv))\nsys.path.insert(0, {str(Path(p.__file__).parent)!r})\n"
                          "import persistence as p\np.notify=lambda errors: print(errors, file=sys.stderr)\n"
                          "p.adapter_capture=lambda tm,pane,dest,ctx,warnings: "
                          "(time.sleep(1), (dest/'unsaved.txt').write_bytes(b'unsaved work'))\n"
                          "raise SystemExit(p.main())\n")
        helper.chmod(0o700)
        config = self.root / "bindings.conf"
        binding = next(line for line in (Path(__file__).parents[2] / "terminal/tmux/tmux.conf").read_text().splitlines()
                       if line.startswith("bind k "))
        config.write_text(binding.replace("context-checkpoint", str(helper)) + "\n")
        self.tm.call("source-file", str(config))
        self.tm.call("bind-key", "j", "select-window", "-t", "work:0")
        archive = shlex.quote(str(helper)) + " pre-kill --socket #{q:socket_path} --operation #{checkpoint_operation} --target-session x#{q:session_id} --target-window x#{q:window_id} --all #{checkpoint_all} --group #{checkpoint_group}"
        self.tm.call("set-option", "-s", "@persistence-checkpoint", archive)
        self.tm.call("set-option", "-p", "-t", self.pane, "@persistence-chat-socket", "/fixture/chat.sock")
        master, slave = pty.openpty()
        client = subprocess.Popen([TMUX, "-S", self.tm.socket, "attach-session", "-t", self.window],
                                  env=dict(os.environ, TERM="xterm-256color"), stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        try:
            deadline = time.monotonic() + 4
            while not self.tm.call("list-clients", "-F", "#{client_session}"):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(.01)
            os.write(master, b"\x02k")
            time.sleep(.1)
            os.write(master, b"y")
            while self.window in self.tm.call("list-windows", "-t", "work", "-F", "#{window_id}").splitlines():
                if time.monotonic() >= deadline:
                    os.set_blocking(master, False)
                    output = os.read(master, 65536)
                    events = p.local_root() / "events.log"
                    argv = self.root / "worker-argv.json"
                    self.fail(f"configured binding never hid tab: {output!r}; argv={argv.read_text() if argv.exists() else ''}; events={events.read_text() if events.exists() else ''}")
                time.sleep(.01)
            marker = self.root / "interactive"
            os.write(master, b"\x02j")
            os.write(master, ("printf ready > " + shlex.quote(str(marker)) + "\r").encode())
            while not marker.exists():
                self.assertLess(time.monotonic(), deadline, "configured binding froze client")
                time.sleep(.01)
            self.assertFalse(list((p.local_root() / "closed-work").glob("*/status.json")))
            statuses = []
            while not statuses:
                self.assertLess(time.monotonic(), deadline)
                statuses = list((p.local_root() / "closed-work").glob("*/status.json"))
                time.sleep(.01)
            self.assertEqual(ctl.read_json(statuses[0])["status"], "saved")
        finally:
            client.terminate()
            client.communicate(timeout=3)
            os.close(master)


if __name__ == "__main__":
    unittest.main()
