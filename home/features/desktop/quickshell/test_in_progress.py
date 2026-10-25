"""Native QML model acceptance against real, isolated context notebooks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "contexts"))
import contextctl as ctl
import context_notes


class InProgressTests(unittest.TestCase):
    def test_native_model(self):
        with tempfile.TemporaryDirectory(prefix="in-progress-") as directory:
            environment = {
                "CONTEXT_ROOT": directory + "/contexts",
                "XDG_STATE_HOME": directory + "/state",
                "QT_QPA_PLATFORM": "offscreen",
                "HYPRLAND_INSTANCE_SIGNATURE": "",
            }
            with patch.dict(os.environ, environment):
                first = ctl.create("First", "/etc/nixos")
                second = ctl.create("Second", "/etc/nixos")
                vault = context_notes.resolve(first["id"])
                for index in range(90):
                    vault.create({"title": f"Work {index:03} with enough text to require pagination",
                                  "body": "Fixture", "status": "In-Progress"})
                vault.create({"title": "Unstarted", "body": "Fixture", "status": "Todo"})
                vault.create({"title": "Only an idea", "body": "Fixture", "status": "Thoughts"})
                vault.create({"title": "Finished", "body": "Fixture", "status": "Done"})
                environment.update(TEST_CONTEXT_FIRST=first["id"], TEST_CONTEXT_SECOND=second["id"])
                result = subprocess.run(
                    ["quickshell", "-p", str(Path(__file__).with_suffix(".qml")), "--no-color"],
                    env={**os.environ, **environment}, capture_output=True, text=True, timeout=25,
                )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output)
            self.assertNotIn("FAILED:", output)
            self.assertIn("PASS: In-Progress", output)


if __name__ == "__main__":
    unittest.main()
