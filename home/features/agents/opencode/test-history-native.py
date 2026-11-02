"""Opt-in real PTY smoke of compiled native history picker; never submits a prompt."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import tempfile
import termios
import sys
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "desktop/contexts"))
from opencode_acceptance_fixture import Screen  # VT model; OpenTUI diff-renders cells


@unittest.skipUnless(os.environ.get("OPENCODE_HISTORY_NATIVE"), "set OPENCODE_HISTORY_NATIVE to compiled binary")
class NativeHistory(unittest.TestCase):
    def test_picker_draws_local_and_portable_then_refreshes_received_head(self):
        here = Path(__file__).resolve().parent
        binary = os.environ["OPENCODE_HISTORY_NATIVE"]
        with tempfile.TemporaryDirectory(prefix="history-native-") as temporary:
            root = Path(temporary)
            home = root / "home"
            home.mkdir()
            env = {**os.environ, "HOME": str(home), "CONTEXT_ROOT": str(root / "contexts"),
                   "XDG_CONFIG_HOME": str(root / "config"), "XDG_STATE_HOME": str(root / "state"),
                   "XDG_DATA_HOME": str(root / "data"), "XDG_CACHE_HOME": str(root / "cache"),
                   "OPENCODE_DB": str(root / "fixture.db"), "OPENCODE_CONTEXT_SCOPE_FILE": str(root / "scope.json"),
                   "OPENCODE_CONTEXT_STATE_FILE": str(root / "state.json"), 
                   "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
                   "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1", "TERM": "xterm-256color",
                   "PYTHONDONTWRITEBYTECODE": "1", "OPENCODE_CONFIG_CONTENT": '{"$schema":"https://opencode.ai/config.json","plugin":[],"snapshot":false}'}
            for key in ("CONTEXT_ID", "CONTEXT_DIRECTORY", "OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "OPENCODE_CONTEXT_HELPER"):
                env.pop(key, None)
            shim = root / "bin"
            shim.mkdir()
            backend = here.parents[1] / "desktop/contexts/context_chat_library.py"
            (shim / "opencode-context-chats").write_text(f'#!/bin/sh\nexec python3 -B "{backend}" "$@"\n')
            (shim / "opencode-context-chats").chmod(0o755)
            env["PATH"] = f"{shim}:{env['PATH']}"
            config = root / "config/opencode"
            config.mkdir(parents=True)
            (config / "tui.json").write_text(json.dumps({"$schema": "https://opencode.ai/tui.json",
                "plugin": [str(here / "tui-plugins/context-library.tsx")]}))
            fixture = here / "history-test-fixture.py"
            owner = json.loads(subprocess.check_output(["python3", str(fixture), "init"], env=env))["owner"]
            env["CONTEXT_ID"] = owner
            (root / "scope.json").write_text(json.dumps({"context_id": owner, "ids": [owner], "hidden": [], "labels": {owner: "Fixture"}}))
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 42, 160, 0, 0))
            process = subprocess.Popen([binary, str(home / "work")], env=env, cwd=root,
                                       stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
            os.close(slave)
            screen = Screen(rows=42, columns=160)

            def wait_for(text, timeout=15):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if text in screen.text:
                        return
                    ready, _, _ = select.select([master], [], [], 0.1)
                    if ready:
                        try:
                            screen.feed(os.read(master, 65536))
                        except OSError:
                            break
                    if process.poll() is not None:
                        break
                self.fail(f"Did not render {text!r}:\n{screen.text}")

            try:
                wait_for("Ask anything")
                wait_for("History: ")  # persistent app_bottom status from context-library plugin
                os.write(master, b"\x18")
                time.sleep(0.1)
                os.write(master, b"l")
                wait_for("Context conversations")
                wait_for("Local fixture")
                wait_for("Portable fixture")
                wait_for("portable_only")
                wait_for("alt+x cancel")
                wait_for("Current as known")
                subprocess.run(["python3", str(fixture), "update"], env=env, check=True, stdout=subprocess.PIPE)
                wait_for("Arrived update", timeout=8)
                self.assertNotIn("Portable fixture", screen.text)
                os.write(master, b"\x1bx")  # alt+x
                wait_for("Selected request cancelled")
                os.write(master, b"\x1br")  # alt+r refresh must not crash or open rename
                time.sleep(1)
                self.assertNotIn("Rename", screen.text)
                wait_for("Arrived update")
                # Fixture index has no transcript objects: selected import must fail
                # visibly, keep the picker open, and never navigate.
                os.write(master, b"\r")
                wait_for("Failed:", timeout=20)
                print("\n" + next(l for l in screen.lines if "Failed:" in l).strip(), file=sys.stderr)
                self.assertIn("Context conversations", screen.text)
                self.assertIn("Local fixture", screen.text)
                self.assertIsNone(process.poll(), "Picker crashed during live refresh")
            finally:
                os.killpg(process.pid, signal.SIGTERM) if process.poll() is None else None
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                os.close(master)


if __name__ == "__main__":
    unittest.main()
