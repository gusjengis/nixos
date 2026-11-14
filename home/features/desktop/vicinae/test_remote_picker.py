import importlib.util
import json
import os
from pathlib import Path
import subprocess
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("picker", Path(__file__).with_name("remote-picker.py"))
picker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(picker)


class RemotePickerTests(unittest.TestCase):
    def test_icons_and_locks_follow_matching_rows(self):
        entries = [("Alpha", "Alpha"), ("Beta", "Beta")]
        rows = [dict(name="Beta", ip="10.0.0.2", password_set=True),
                dict(name="Alpha", ip="10.0.0.1", password_set=False)]
        result = [row.split("\t") for row in picker.picker_rows(entries, rows)]
        self.assertEqual(result[0][0], "Alpha")
        self.assertTrue(result[0][1].endswith("/windows-tile-pending.svg"))
        self.assertTrue(result[0][2].endswith("/password-lock.svg"))
        self.assertTrue(result[1][1].endswith("/windows-tile-pending.svg"))
        self.assertEqual(result[1][2], "")
        self.assertEqual([row[3] for row in result], ["10.0.0.1", "10.0.0.2"])

    def test_public_listing_reuses_validation_and_never_returns_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "remotes.csv"
            path.write_text("name,ip,domain_user,password\nTest,10.0.0.1,DOMAIN\\user,secret-sentinel\n")
            self.assertEqual(picker.list_remotes(path), [
                dict(name="Test", ip="10.0.0.1", password_set=True)])
            path.write_text("name,ip,domain_user,password\nTest,not-an-ip,user,secret-sentinel\n")
            with self.assertRaisesRegex(ValueError, "Invalid IP"):
                picker.list_remotes(path)

    def test_non_csv_entries_keep_original_icons(self):
        result = picker.picker_rows([("VM", "/vm.desktop")])
        self.assertEqual(len(result[0].split("\t")), 2)
        self.assertTrue(result[0].endswith("/windows-tile.svg"))

    def test_picker_lock_released_before_launch_and_no_state_query(self):
        rows = [dict(name="Test", ip="10.0.0.1", password_set=True)]
        with tempfile.TemporaryDirectory() as directory:
            def run(command, **kwargs):
                if command == ["conference-rdp", "--list"]:
                    return subprocess.CompletedProcess(command, 0, json.dumps(rows))
                with (Path(directory) / "conference-remotes.lock").open("w") as contender:
                    if command[:2] == ["vicinae", "dmenu"]:
                        with self.assertRaises(BlockingIOError):
                            picker.fcntl.flock(contender, picker.fcntl.LOCK_EX | picker.fcntl.LOCK_NB)
                        return subprocess.CompletedProcess(command, 0, "0\n")
                    self.assertEqual(command, ["conference-rdp", "--launch", "Test"])
                    picker.fcntl.flock(contender, picker.fcntl.LOCK_EX | picker.fcntl.LOCK_NB)
                    return subprocess.CompletedProcess(command, 0)

            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}), \
                 patch.object(picker.sys, "argv", ["remote-picker", "--csv"]), \
                 patch.object(picker.subprocess, "run", side_effect=run):
                picker.main()

    def test_second_invocation_closes_picker_without_competing_menu(self):
        with tempfile.TemporaryDirectory() as directory:
            with (Path(directory) / "conference-remotes.lock").open("w") as owner:
                picker.fcntl.flock(owner, picker.fcntl.LOCK_EX | picker.fcntl.LOCK_NB)
                with patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}), \
                     patch.object(picker.sys, "argv", ["remote-picker", "--csv"]), \
                     patch.object(picker, "list_remotes") as listing, \
                     patch.object(picker.subprocess, "run", return_value=
                         subprocess.CompletedProcess([], 0)) as run:
                    picker.main()
                    self.assertEqual(run.call_args.args[0], ["vicinae", "close"])
                    self.assertGreater(run.call_args.kwargs["timeout"], 0)
                    self.assertLessEqual(run.call_args.kwargs["timeout"], 2)
                    self.assertEqual(run.call_count, 1)
                    listing.assert_not_called()

    def test_toggle_before_menu_maps_retries_close(self):
        with tempfile.TemporaryDirectory() as directory:
            with (Path(directory) / "conference-remotes.lock").open("w") as owner:
                picker.fcntl.flock(owner, picker.fcntl.LOCK_EX | picker.fcntl.LOCK_NB)
                with patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}), \
                     patch.object(picker.sys, "argv", ["remote-picker", "--csv"]), \
                     patch.object(picker.subprocess, "run", side_effect=[
                         subprocess.CompletedProcess([], 1),
                         subprocess.CompletedProcess([], 0)]) as run:
                    picker.main()
                    self.assertEqual(run.call_count, 2)

    def test_direct_listing_shows_menu_without_subprocess_listing(self):
        rows = [dict(name="Test", ip="10.0.0.1", password_set=False)]
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}), \
                 patch.object(picker.sys, "argv", ["remote-picker", "--csv", "--csv-file", "private.csv"]), \
                 patch.object(picker, "list_remotes", return_value=rows) as listing, \
                 patch.object(picker.subprocess, "run", return_value=
                     subprocess.CompletedProcess([], 0, "")) as run:
                picker.main()
                listing.assert_called_once_with("private.csv")
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][:2], ["vicinae", "dmenu"])
                self.assertTrue(run.call_args.kwargs["input"].endswith("\t10.0.0.1"))

    def test_status_snapshot_is_private_complete_and_credential_free(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            picker.write_status(runtime, {"10.0.0.1": False})
            path = runtime / "conference-remotes-status.json"
            data = json.loads(path.read_text())
            self.assertEqual(set(data), {"checked_at", "hosts"})
            self.assertEqual(data["hosts"], {"10.0.0.1": False})
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(list(runtime.iterdir()), [path])
            picker.write_status(runtime, {"10.0.0.2": True})
            self.assertEqual(json.loads(path.read_text())["hosts"], {"10.0.0.2": True})

    def test_monitor_publishes_status_without_waiting_for_menu_open(self):
        rows = [dict(name="Test", ip="10.0.0.1", password_set=True)]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(picker, "list_remotes", return_value=rows), \
                 patch.object(picker, "probe_status", return_value=False), \
                 patch.object(picker.time, "sleep", side_effect=InterruptedError):
                with self.assertRaises(InterruptedError):
                    picker.watch_status("private.csv", Path(directory))
            data = json.loads((Path(directory) / "conference-remotes-status.json").read_text())
            self.assertEqual(data["hosts"], {"10.0.0.1": False})

    def test_monitor_checks_only_rdp_with_bounded_timeout(self):
        with patch.object(socket, "create_connection") as connect:
            self.assertTrue(picker.probe_status("10.0.0.1"))
            connect.assert_called_once_with(("10.0.0.1", 3389), timeout=0.6)
        with patch.object(socket, "create_connection", side_effect=socket.timeout):
            self.assertFalse(picker.probe_status("10.0.0.1"))


if __name__ == "__main__":
    unittest.main()
