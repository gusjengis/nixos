"""One fixed privileged operation: select Windows for one boot, then reboot."""

import os
import re
import subprocess
import sys

EFIBOOTMGR = "@efibootmgr@"
SYSTEMCTL = "@systemctl@"


def windows_entry(output):
    entries = re.findall(
        r"^Boot([0-9A-Fa-f]{4})\*[ \t]+Windows Boot Manager[ \t]+.*"
        r"/(?:File\()?\\EFI\\Microsoft\\Boot\\bootmgfw\.efi(?:\)|[0-9A-Fa-f]*$)",
        output,
        re.MULTILINE | re.IGNORECASE,
    )
    if len(entries) != 1:
        raise RuntimeError("Expected exactly one active Windows Boot Manager entry.")
    return entries[0].upper()


def next_boot(output):
    match = re.search(r"^BootNext:\s*([0-9A-Fa-f]{4})\s*$", output, re.MULTILINE)
    return match[1].upper() if match else None


def reboot(run=subprocess.run):
    def command(*args):
        return run(args, check=True, capture_output=True, text=True).stdout

    before = command(EFIBOOTMGR, "--verbose")
    target = windows_entry(before)
    previous = next_boot(before)
    try:
        command(EFIBOOTMGR, "--bootnext", target)
        if next_boot(command(EFIBOOTMGR, "--verbose")) != target:
            raise RuntimeError("Firmware did not accept the one-time Windows boot.")
        command(SYSTEMCTL, "reboot")
    except Exception:
        # Failed reboot must not leave a surprise Windows boot queued.
        if previous is None:
            command(EFIBOOTMGR, "--delete-bootnext")
        else:
            command(EFIBOOTMGR, "--bootnext", previous)
        raise


if __name__ == "__main__":
    if len(sys.argv) != 1 or os.geteuid() != 0:
        sys.exit("This helper requires root and accepts no arguments.")
    try:
        reboot()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        detail = error.stderr if isinstance(error, subprocess.CalledProcessError) else str(error)
        sys.exit(f"Windows reboot failed: {detail}")
