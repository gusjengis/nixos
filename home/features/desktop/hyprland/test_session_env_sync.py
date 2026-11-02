"""Startup must attempt remaining services after one service fails."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class SessionEnvSyncTests(unittest.TestCase):
    def test_missing_service_does_not_block_context_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "calls"
            systemctl = root / "systemctl"
            systemctl.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
                'if [ "$2" = restart ] && [ "$4" = missing.service ]; then exit 5; fi\n'
            )
            systemctl.chmod(0o755)
            dbus = root / "dbus-update-activation-environment"
            dbus.write_text('#!/bin/sh\nprintf "dbus %s\\n" "$*" >> "$CALL_LOG"\n')
            dbus.chmod(0o755)
            result = subprocess.run(
                ["bash", str(Path(__file__).with_name("session-env-sync.sh")),
                 "missing.service", "desktop-contexts.service", "context-shutdown-barrier.service"],
                env={**os.environ, "PATH": f"{root}:{os.environ['PATH']}",
                     "CALL_LOG": str(log), "WAYLAND_DISPLAY": "wayland-test"},
                capture_output=True, text=True,
            )
            calls = log.read_text().splitlines()
            self.assertEqual(result.returncode, 1)
            self.assertIn("failed to restart missing.service", result.stderr)
            self.assertIn("--user restart --no-block desktop-contexts.service", calls)
            self.assertIn("--user restart --no-block context-shutdown-barrier.service", calls)
            self.assertTrue(calls[0].startswith("--user import-environment "))
            self.assertTrue(calls[1].startswith("dbus --systemd "))


if __name__ == "__main__":
    unittest.main()
