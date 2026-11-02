"""Exercise exit failure paths without dispatching any desktop action."""

import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import session_exit as exit_module


class SessionExitTests(unittest.TestCase):
    def exercise(self, code=None, *, timeout=2, missing=False, broken_log=False):
        spawn = subprocess.Popen
        children = []

        def checkpoint(args, **kwargs):
            self.assertEqual(args, ["context-checkpoint", "save", "--reason", "compositor-exit"])
            if missing:
                raise FileNotFoundError("context-checkpoint missing")
            child = spawn([sys.executable, "-c", code], **kwargs)
            children.append(child)
            return child

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"
            if broken_log:
                state.write_text("not a directory")
            with patch.dict(os.environ, XDG_STATE_HOME=str(state)), patch.object(
                exit_module.subprocess, "Popen", checkpoint
            ), patch.object(exit_module.subprocess, "call", return_value=0) as action, patch.object(
                exit_module, "CHECKPOINT_TIMEOUT", timeout
            ), patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(exit_module.main(), 0)
                action.assert_called_once_with(["hyprctl", "dispatch", "exit"])
            for child in children:
                self.assertIsNotNone(child.poll())
            log = state / "desktop-contexts/terminal/events.log"
            return log.read_text() if log.exists() else ""

    def test_success(self):
        self.assertIn("exit requested", self.exercise("pass"))

    def test_failed_save_keeps_diagnostics_and_exits(self):
        log = self.exercise("import sys; print('network directory missing', file=sys.stderr); sys.exit(1)")
        self.assertIn("network directory missing", log)
        self.assertIn("exiting anyway", log)

    def test_hung_save_is_killed_and_exits(self):
        self.assertIn("exiting anyway", self.exercise("import time; time.sleep(60)", timeout=.05))

    def test_missing_checkpoint_exits(self):
        self.assertIn("context-checkpoint missing", self.exercise(missing=True))

    def test_unwritable_log_and_failed_checkpoint_still_exit(self):
        self.exercise(missing=True, broken_log=True)


if __name__ == "__main__":
    unittest.main()
