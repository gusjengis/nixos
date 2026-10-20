"""Native barrier integration tests; PERSISTENCE_TMUX must name patched tmux.

Run: PERSISTENCE_TMUX=/nix/store/.../bin/tmux python3 -m unittest discover \
    -s home/features/terminal/tmux -p test_checkpoint.py -v
All servers, helper scripts, and sockets belong to a fresh /tmp/opencode fixture.
The native option is server-scoped: set-option -s @persistence-checkpoint.
"""

import json
import os
from pathlib import Path
import pty
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


HELPER = r'''
import json, pathlib, subprocess, sys, time
binary, socket, root, mode = sys.argv[1:]
root = pathlib.Path(root)
base = [binary, "-S", socket]
probe = subprocess.run(base + ["list-panes", "-a", "-F",
    "#{session_name}|#{window_id}|#{pane_id}"], capture_output=True, text=True)
record = {"status": probe.returncode, "panes": probe.stdout.splitlines(),
          "stderr": probe.stderr}
if mode == "recursive":
    result = subprocess.run(base + ["kill-session", "-t", "victim"],
                            capture_output=True, text=True, timeout=3)
    record["recursive_status"] = result.returncode
    record["recursive_stderr"] = result.stderr
tmp = root / "snapshot.tmp"
tmp.write_text(json.dumps(record))
tmp.replace(root / "snapshot.json")
if mode in ("wait", "recursive"):
    deadline = time.monotonic() + 8
    while not (root / "release").exists():
        if time.monotonic() > deadline:
            sys.exit(99)
        time.sleep(.01)
sys.exit(23 if mode == "fail" else 0)
'''


@unittest.skipUnless(os.environ.get("PERSISTENCE_TMUX"),
                     "set PERSISTENCE_TMUX to patched tmux binary")
class NativeCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.binary = shutil.which(os.environ["PERSISTENCE_TMUX"])
        self.assertIsNotNone(self.binary, "PERSISTENCE_TMUX is not executable")
        Path("/tmp/opencode").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="checkpoint-", dir="/tmp/opencode")
        self.root = Path(self.temp.name)
        self.socket = str(self.root / "socket")
        self.base = [self.binary, "-S", self.socket, "-f", "/dev/null"]
        self.env = dict(os.environ, TMUX="", TERM="xterm-256color")
        self.children = []
        self.helper = self.root / "helper.py"
        self.helper.write_text(HELPER)
        self.tmux("new-session", "-d", "-s", "anchor", "sleep 60")
        self.tmux("set-option", "-g", "exit-empty", "on")
        self.tmux("new-session", "-d", "-s", "victim", "sleep 60")

    def tearDown(self):
        (self.root / "release").touch()
        self.tmux("set-option", "-su", "@persistence-checkpoint", check=False)
        self.tmux("kill-server", check=False)
        for child in self.children:
            if child.poll() is None:
                child.terminate()
            try:
                child.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
        self.temp.cleanup()

    def tmux(self, *args, check=True):
        result = subprocess.run(self.base + list(args), env=self.env,
                                capture_output=True, text=True, timeout=5)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def start(self, *args):
        child = subprocess.Popen(self.base + list(args), env=self.env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 text=True)
        self.children.append(child)
        return child

    def configure(self, mode="wait", timeout=False):
        command = [sys.executable, str(self.helper), self.binary,
                   self.socket, str(self.root), mode]
        if timeout:
            executable = shutil.which("timeout")
            self.assertIsNotNone(executable, "GNU timeout required")
            command = [executable, "0.4s"] + command
        self.command = shlex.join(command)
        self.tmux("set-option", "-s", "@persistence-checkpoint", self.command)

    def snapshot(self):
        deadline = time.monotonic() + 4
        path = self.root / "snapshot.json"
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(path.exists(), "checkpoint helper never queried server")
        data = json.loads(path.read_text())
        self.assertEqual(data["status"], 0, data["stderr"])
        return data

    def panes(self):
        return self.tmux("list-panes", "-a", "-F",
                         "#{session_name}|#{window_id}|#{pane_id}").stdout.splitlines()

    def finish(self, child, success=True):
        (self.root / "release").touch()
        stdout, stderr = child.communicate(timeout=5)
        if success:
            self.assertEqual(child.returncode, 0, stderr)
        else:
            self.assertNotEqual(child.returncode, 0, stdout)
        return stderr

    def assert_held(self, child, before):
        self.assertEqual(self.snapshot()["panes"], before)
        self.assertIsNone(child.poll(), "destruction completed before helper")
        self.assertEqual(self.panes(), before)
        self.assertEqual(self.tmux("display-message", "-p", "queue-alive").stdout.strip(),
                         "queue-alive")

    def test_success_precedes_deletion_and_following_command(self):
        before = self.panes()
        self.configure()
        child = self.start("kill-session", "-t", "victim", ";",
                           "set-option", "-g", "@after", "yes")
        self.assert_held(child, before)
        self.assertEqual(self.tmux("show-options", "-gqv", "@after").stdout, "")
        self.finish(child)
        self.assertTrue(all(row.startswith("anchor|") for row in self.panes()))
        self.assertEqual(self.tmux("show-options", "-gqv", "@after").stdout.strip(), "yes")

    def test_kill_session_all_other(self):
        self.tmux("new-session", "-d", "-s", "other", "sleep 60")
        before = self.panes()
        self.configure()
        child = self.start("kill-session", "-a", "-t", "anchor")
        self.assert_held(child, before)
        self.finish(child)
        self.assertEqual(self.tmux("list-sessions", "-F", "#{session_name}").stdout,
                         "anchor\n")

    def test_kill_session_group(self):
        self.tmux("new-session", "-d", "-t", "victim", "-s", "grouped")
        before = self.panes()
        self.configure()
        child = self.start("kill-session", "-g", "-t", "victim")
        self.assert_held(child, before)
        self.finish(child)
        self.assertEqual(self.tmux("list-sessions", "-F", "#{session_name}").stdout,
                         "anchor\n")

    def test_kill_window_all_other(self):
        self.tmux("new-window", "-d", "-t", "victim:1", "sleep 60")
        self.tmux("new-window", "-d", "-t", "victim:2", "sleep 60")
        before = self.panes()
        self.configure()
        child = self.start("kill-window", "-a", "-t", "victim:0")
        self.assert_held(child, before)
        self.finish(child)
        self.assertEqual(self.tmux("list-windows", "-t", "victim", "-F",
                                   "#{window_index}").stdout, "0\n")
        self.assertEqual(len(self.panes()), 2)

    def test_kill_pane_all_other(self):
        keep = self.tmux("display-message", "-p", "-t", "victim:0.0",
                         "#{pane_id}").stdout.strip()
        self.tmux("split-window", "-d", "-t", "victim:0", "sleep 60")
        self.tmux("split-window", "-d", "-t", "victim:0", "sleep 60")
        before = self.panes()
        self.configure()
        child = self.start("kill-pane", "-a", "-t", keep)
        self.assert_held(child, before)
        self.finish(child)
        self.assertEqual(self.tmux("list-panes", "-t", "victim:0", "-F",
                                   "#{pane_id}").stdout.strip(), keep)
        self.assertEqual(len(self.panes()), 2)

    def test_kill_server(self):
        before = self.panes()
        self.configure()
        child = self.start("kill-server")
        self.assert_held(child, before)
        self.finish(child)
        self.assertNotEqual(self.tmux("list-sessions", check=False).returncode, 0)

    def test_failure_discards_rest_of_same_command_group(self):
        before = self.panes()
        self.configure("fail")
        child = self.start("set-option", "-g", "@before", "yes", ";",
                           "kill-session", "-t", "victim", ";",
                           "set-option", "-g", "@after", "yes")
        self.assertEqual(self.snapshot()["panes"], before)
        self.assertIn("checkpoint failed or timed out", self.finish(child, success=False))
        self.assertEqual(self.panes(), before)
        self.assertEqual(self.tmux("show-options", "-gqv", "@before").stdout.strip(), "yes")
        self.assertEqual(self.tmux("show-options", "-gqv", "@after").stdout, "")
        # Failure must release the busy latch and leave later queues operational.
        self.configure("success")
        self.tmux("kill-session", "-t", "victim")

    def test_shell_timeout_preserves_target_and_queue(self):
        before = self.panes()
        self.configure(timeout=True)
        child = self.start("kill-session", "-t", "victim")
        self.assertEqual(self.snapshot()["panes"], before)
        self.assertIn("checkpoint failed or timed out", self.finish_without_release(child))
        self.assertEqual(self.panes(), before)
        self.configure("success")
        self.tmux("kill-session", "-t", "victim")

    def finish_without_release(self, child):
        stdout, stderr = child.communicate(timeout=5)
        self.assertNotEqual(child.returncode, 0, stdout)
        return stderr

    def test_concurrent_and_recursive_destruction_rejected(self):
        before = self.panes()
        self.configure("recursive")
        child = self.start("kill-session", "-t", "victim")
        self.assert_held(child, before)
        record = self.snapshot()
        self.assertNotEqual(record["recursive_status"], 0)
        self.assertIn("checkpoint in progress", record["recursive_stderr"])
        result = self.tmux("kill-window", "-t", "anchor:0", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checkpoint in progress", result.stderr)
        self.assertEqual(self.panes(), before)
        self.finish(child)
        self.configure("success")
        self.tmux("kill-window", "-t", "anchor:0")

    def test_disappeared_target_does_not_stall_queue(self):
        self.tmux("new-window", "-d", "-t", "victim:1", "sleep 60")
        before = self.panes()
        self.configure()
        child = self.start("kill-window", "-t", "victim:1", ";",
                           "set-option", "-g", "@after", "yes")
        self.assert_held(child, before)
        # Simulate independent disappearance without sending another checkpoint.
        self.tmux("set-option", "-su", "@persistence-checkpoint")
        self.tmux("kill-window", "-t", "victim:1")
        self.tmux("set-option", "-s", "@persistence-checkpoint", self.command)
        self.finish(child, success=False)
        self.assertEqual(self.tmux("show-options", "-gqv", "@after").stdout, "")
        self.assertEqual(len(self.panes()), 2)
        self.configure("success")
        self.tmux("kill-session", "-t", "victim")

    def test_replaced_target_is_not_destroyed(self):
        before = self.panes()
        self.configure()
        child = self.start("kill-session", "-t", "victim")
        self.assert_held(child, before)
        self.tmux("set-option", "-su", "@persistence-checkpoint")
        self.tmux("kill-session", "-t", "victim")
        self.tmux("new-session", "-d", "-s", "victim", "sleep 60")
        replacement = self.panes()
        self.tmux("set-option", "-s", "@persistence-checkpoint", self.command)
        self.assertRegex(self.finish(child, success=False), "(?:checkpoint target|tmux topology) changed")
        self.assertEqual(self.panes(), replacement)

    def test_tree_mode_tagged_X_uses_checkpoint(self):
        # A real terminal client supplies mode-tree's client context. Separate
        # send-keys commands exercise the actual interactive X confirmation path.
        master, slave = pty.openpty()
        client = subprocess.Popen(self.base + ["attach-session", "-t", "victim"],
                                  env=self.env, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        self.children.append(client)
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if self.tmux("list-clients", "-F", "#{client_session}").stdout.strip():
                    break
                time.sleep(.01)
            else:
                self.fail("terminal client failed to attach")
            self.tmux("choose-tree", "-s", "-t", "victim:0")
            self.assertEqual(self.tmux("display-message", "-p", "-t", "victim:0",
                                      "#{pane_in_mode}").stdout.strip(), "1")
            before = self.panes()
            self.configure()
            target_client = self.tmux("list-clients", "-F", "#{client_name}").stdout.strip()
            self.tmux("send-keys", "-K", "-c", target_client, "t", "X")
            # Confirmation lives on the client, not in the pane's mode key table.
            self.tmux("send-keys", "-K", "-c", target_client, "y")
            self.assertEqual(self.snapshot()["panes"], before)
            self.assertEqual(self.panes(), before)
            (self.root / "release").touch()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if all(row.startswith("anchor|") for row in self.panes()):
                    break
                time.sleep(.01)
            self.assertTrue(all(row.startswith("anchor|") for row in self.panes()))
        finally:
            os.close(master)


if __name__ == "__main__":
    unittest.main()
