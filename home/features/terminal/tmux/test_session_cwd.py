"""Isolated-server coverage for reopening a context terminal."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("tmux"), "tmux unavailable")
class SessionWorkingDirectoryTests(unittest.TestCase):
    def test_reopen_updates_default_without_moving_pane_or_replacing_environment(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as temporary:
            root = Path(temporary)
            work = root / "repo work #1"
            work.mkdir()
            binary = shutil.which("tmux")
            base = [binary, "-S", str(root / "socket")]

            def tmux(*args):
                return subprocess.check_output([*base, *args], text=True).strip()

            tmux("-f", "/dev/null", "new-session", "-d", "-s", "context-fixture",
                 "-c", str(root), "sleep 60")
            try:
                tmux("set-environment", "-t", "context-fixture", "CONTEXT_ID", "original")
                wrapper = root / "tmux"
                wrapper.write_text("#!/bin/sh\nexec " + shlex.join(base) + ' "$@"\n')
                wrapper.chmod(0o755)
                env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                           TMUX=str(root / "socket") + ",123,0", CONTEXT_ID="unrelated")
                result = subprocess.run(["bash", str(Path(__file__).with_name("create_tmux_session.sh")),
                                         str(work), "context-fixture"], env=env,
                                        text=True, capture_output=True, timeout=5, check=True)
                self.assertEqual(result.stdout.strip(), "context-fixture")
                self.assertEqual(tmux("display-message", "-p", "-t", "context-fixture",
                                      "#{session_path}"), str(work))
                self.assertEqual(tmux("display-message", "-p", "-t", "context-fixture",
                                      "#{pane_current_path}"), str(root))
                self.assertEqual(tmux("show-environment", "-t", "context-fixture", "CONTEXT_ID"),
                                 "CONTEXT_ID=original")
                self.assertEqual(tmux("display-message", "-p", "-t", "context-fixture",
                                      "#{session_attached}"), "0")
            finally:
                tmux("kill-server")


if __name__ == "__main__":
    unittest.main()
