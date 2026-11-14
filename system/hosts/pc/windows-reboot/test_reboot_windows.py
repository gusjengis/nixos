import subprocess
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from reboot_windows import EFIBOOTMGR, SYSTEMCTL, next_boot, reboot, windows_entry


ENTRY = (
    "BootCurrent: 0007\nBootOrder: 0007,0002,0001,0000,0003\n"
    r"Boot0000* Windows Boot Manager HD(1,GPT,example)/File(\EFI\Microsoft\Boot\bootmgfw.efi)"
    "\n"
)


class RebootTests(unittest.TestCase):
    def run_case(self, before=ENTRY, after="BootNext: 0000\n" + ENTRY, fail=None):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            self.assertEqual(kwargs, dict(check=True, capture_output=True, text=True))
            if args == fail:
                raise subprocess.CalledProcessError(1, args, stderr="Test failure")
            output = before if len(calls) == 1 else after
            return SimpleNamespace(stdout=output)

        return calls, lambda: reboot(run)

    def test_windows_entry(self):
        self.assertEqual(windows_entry(ENTRY), "0000")
        self.assertEqual(windows_entry(ENTRY.replace("Boot0000", "Boot00af")), "00AF")

    def test_firmware_output_without_file_wrapper(self):
        # Current efibootmgr prints the path directly, followed by hex optional data.
        output = ENTRY.replace("/File(", "/").replace(".efi)", ".efi57494e444f575300")
        self.assertEqual(windows_entry(output), "0000")
        self.assertEqual(windows_entry(output.upper().replace("BOOT0000", "Boot0000")), "0000")

    def test_reject_missing_duplicate_inactive_or_wrong_path(self):
        for output in ("", ENTRY + ENTRY, ENTRY.replace("0000*", "0000 "),
                       ENTRY.replace("bootmgfw.efi", "other.efi")):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                windows_entry(output)

    def test_next_boot(self):
        self.assertIsNone(next_boot(ENTRY))
        self.assertEqual(next_boot("BootNext: 00af\n" + ENTRY), "00AF")

    def test_success_sets_only_bootnext_then_reboots(self):
        calls, action = self.run_case()
        action()
        self.assertEqual(calls, [
            (EFIBOOTMGR, "--verbose"),
            (EFIBOOTMGR, "--bootnext", "0000"),
            (EFIBOOTMGR, "--verbose"),
            (SYSTEMCTL, "reboot"),
        ])

    def test_missing_windows_never_writes_or_reboots(self):
        calls, action = self.run_case(before="BootOrder: 0007\n")
        with self.assertRaises(RuntimeError):
            action()
        self.assertEqual(calls, [(EFIBOOTMGR, "--verbose")])

    def test_reboot_failure_clears_override(self):
        calls, action = self.run_case(fail=(SYSTEMCTL, "reboot"))
        with self.assertRaises(subprocess.CalledProcessError):
            action()
        self.assertEqual(calls[-1], (EFIBOOTMGR, "--delete-bootnext"))

    def test_reboot_failure_restores_previous_override(self):
        calls, action = self.run_case(before="BootNext: 0002\n" + ENTRY,
                                      fail=(SYSTEMCTL, "reboot"))
        with self.assertRaises(subprocess.CalledProcessError):
            action()
        self.assertEqual(calls[-1], (EFIBOOTMGR, "--bootnext", "0002"))

    def test_firmware_rejects_override_never_reboots(self):
        calls, action = self.run_case(after=ENTRY)
        with self.assertRaises(RuntimeError):
            action()
        self.assertNotIn((SYSTEMCTL, "reboot"), calls)
        self.assertEqual(calls[-1], (EFIBOOTMGR, "--delete-bootnext"))

    def test_write_failure_never_reboots(self):
        calls, action = self.run_case(fail=(EFIBOOTMGR, "--bootnext", "0000"))
        with self.assertRaises(subprocess.CalledProcessError):
            action()
        self.assertNotIn((SYSTEMCTL, "reboot"), calls)


class LauncherTests(unittest.TestCase):
    def launch(self, question, helper):
        source = Path(__file__).with_name("default.nix").read_text()
        script = source.split("    text = ''\n", 1)[1].split("    '';", 1)[0]
        # Exercise the production shell, but make privileged execution impossible.
        script = script.replace("/run/wrappers/bin/sudo", "mock_sudo")
        script = script.replace("${helper}", "/immutable/helper")
        mocks = '''
set -euo pipefail
zenity() {
    printf '%s\\n' "$*" >> "$LOG"
    if [[ "$1" == --question ]]; then return "$QUESTION"; fi
}
mock_sudo() {
    echo sudo >> "$LOG"
    echo "Test error" >&2
    return "$HELPER"
}
'''
        with tempfile.TemporaryDirectory(prefix="windows-launcher-", dir="/tmp/opencode") as directory:
            log = Path(directory) / "log"
            result = subprocess.run(
                ["bash", "-c", mocks + script], capture_output=True, text=True,
                env={**os.environ, "LOG": str(log), "QUESTION": str(question), "HELPER": str(helper)},
            )
            return result.returncode, log.read_text()

    def test_cancel_never_calls_helper(self):
        status, log = self.launch(question=1, helper=0)
        self.assertEqual(status, 0)
        self.assertNotIn("sudo\n", log)
        self.assertIn("--default-cancel", log)

    def test_confirm_calls_helper(self):
        status, log = self.launch(question=0, helper=0)
        self.assertEqual(status, 0)
        self.assertIn("sudo\n", log)
        self.assertNotIn("--error", log)

    def test_helper_failure_displays_error(self):
        status, log = self.launch(question=0, helper=1)
        self.assertEqual(status, 1)
        self.assertIn("--error", log)
        self.assertIn("Test error", log)


if __name__ == "__main__":
    unittest.main()
