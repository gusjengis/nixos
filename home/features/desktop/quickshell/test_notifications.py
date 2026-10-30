"""Exercise real notification delivery on an isolated session bus."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


QML = str(Path(__file__).with_suffix(".qml"))


def exercise():
    with tempfile.TemporaryFile(mode="w+") as log:
        shell = subprocess.Popen(
            ["quickshell", "-p", QML, "--no-color"], stdout=log, stderr=log,
            env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "HYPRLAND_INSTANCE_SIGNATURE": ""},
        )

        def ipc(method, *args):
            return subprocess.check_output(
                ["quickshell", "-p", QML, "ipc", "call", "testNotifications", method, *args],
                text=True, stderr=subprocess.DEVNULL, timeout=5,
            ).strip()

        def wait_for(predicate):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                try:
                    state = json.loads(ipc("state"))
                    if predicate(state):
                        return state
                except (subprocess.CalledProcessError, json.JSONDecodeError):
                    pass
                time.sleep(0.05)
            raise AssertionError(f"Notification state did not converge: {locals().get('state')}")

        def send(summary, *options):
            return subprocess.check_output(
                ["notify-send", "-p", "-t", "0", *options, summary], text=True, timeout=5,
            ).strip()

        try:
            wait_for(lambda state: not state["dnd"])
            replacement = send("normal")
            send("transient", "-h", "boolean:transient:true")
            wait_for(lambda state: len(state["popups"]) == 2 and state["entries"] == 2)

            ipc("setDnd", "true")
            state = wait_for(lambda state: state["dnd"] and not state["popups"] and state["entries"] == 1)
            assert state["history"] == ["normal"], state

            send("critical", "-u", "critical")
            send("quiet transient", "-h", "boolean:transient:true")
            send("updated", "-r", replacement)
            state = wait_for(lambda state: state["history"] == ["updated", "critical"] and state["entries"] == 2)
            assert not state["popups"], state

            ipc("setDnd", "false")
            state = wait_for(lambda state: not state["dnd"])
            assert not state["popups"], state  # No backlog replay.
            send("resumed")
            state = wait_for(lambda state: state["popups"] == ["resumed"])
            assert state["history"] == ["resumed", "updated", "critical"], state
        finally:
            shell.terminate()
            shell.wait(timeout=5)
            log.seek(0)
            output = log.read()
            print(output)
            assert "ERROR" not in output and "TypeError" not in output, output


class NotificationTests(unittest.TestCase):
    def test_do_not_disturb(self):
        result = subprocess.run(
            ["dbus-run-session", "--", sys.executable, __file__, "--isolated"],
            capture_output=True, text=True, timeout=45,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    if "--isolated" in sys.argv:
        exercise()
    else:
        unittest.main()
