"""Present configured RDP desktop entries using Vicinae's existing glass UI."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def list_remotes(csv_file):
    # Share validation with the connection helper, without a second interpreter.
    # Only public row fields cross into the picker and its IPC payload.
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "remote/windows-vm/csv-rdp.py"
    spec = importlib.util.spec_from_file_location("csv_rdp", path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    return [{"name": row["name"], "ip": row["ip"],
             "password_set": bool(row["password"])} for row in helper.read_remotes(csv_file)]


def picker_rows(entries, csv_rows=None):
    assets = Path(__file__).parent
    if csv_rows is None:
        return [f"{name}\t{assets / 'windows-tile.svg'}" for name, _ in entries]
    by_name = {row["name"]: row for row in csv_rows}
    rows = []
    for name, _ in entries:
        # Vicinae reads the background monitor's current snapshot before mapping.
        icon = assets / "windows-tile-pending.svg"
        lock = str(assets / "password-lock.svg") if not by_name[name]["password_set"] else ""
        rows.append(f"{name}\t{icon}\t{lock}\t{by_name[name]['ip']}")
    return rows


def remotes(manifest):
    import configparser
    entries = []
    for path in manifest:
        desktop = configparser.ConfigParser(interpolation=None, strict=False)
        desktop.read(path)
        if desktop.has_section("Desktop Entry"):
            entries.append((desktop["Desktop Entry"]["Name"], path))
    return sorted(entries)


def probe_status(address):
    import socket
    try:
        with socket.create_connection((address, 3389), timeout=0.6):
            return True
    except OSError:
        return False


def write_status(runtime, hosts):
    import tempfile
    # Atomic replacement: readers see one complete, private, credential-free snapshot.
    path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=runtime, prefix=".remote-status-",
                                         delete=False) as output:
            path = Path(output.name)
            json.dump({"checked_at": time.time(), "hosts": hosts}, output)
        path.replace(runtime / "conference-remotes-status.json")
    finally:
        if path is not None:
            path.unlink(missing_ok=True)


def watch_status(csv_file, runtime):
    from concurrent.futures import ThreadPoolExecutor
    with (runtime / "conference-remotes-status.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with ThreadPoolExecutor(max_workers=16) as pool:
            while True:
                try:
                    addresses = sorted({row["ip"] for row in list_remotes(csv_file)})
                    hosts = dict(zip(addresses, pool.map(probe_status, addresses)))
                    write_status(runtime, hosts)
                except (OSError, ValueError) as error:
                    print(f"Remote status: {error}", file=sys.stderr, flush=True)
                time.sleep(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--csv", action="store_true")
    parser.add_argument("--csv-file")
    parser.add_argument("--watch-status", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    # The state-query IPC can hang indefinitely. Own only the visible picker,
    # so another keypress closes it without spawning a competing dmenu request.
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    if args.watch_status:
        if not args.csv_file:
            parser.error("--watch-status requires --csv-file")
        watch_status(args.csv_file, runtime)
        return
    with (runtime / "conference-remotes.lock").open("w") as lock:
        if not args.list:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                # A second press may arrive before the first menu has mapped.
                # Retry "already closed" until it maps or its owner exits.
                deadline = time.monotonic() + 2
                while (remaining := deadline - time.monotonic()) > 0:
                    try:
                        result = subprocess.run(["vicinae", "close"], check=False, timeout=remaining,
                                                capture_output=True)
                    except subprocess.TimeoutExpired:
                        break
                    if result.returncode == 0:
                        break
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        time.sleep(0.01)
                return
        csv_rows = None
        if args.csv:
            if args.csv_file:
                csv_rows = list_remotes(args.csv_file)
            else:
                listed = subprocess.run(["conference-rdp", "--list"], check=True, capture_output=True, text=True)
                csv_rows = json.loads(listed.stdout)
            entries = sorted((row["name"], row["name"]) for row in csv_rows)
        else:
            with open(args.manifest) as source:
                entries = remotes(json.load(source))
        if args.list:
            print(json.dumps(entries))
            return
        if not entries:
            return
        choice = subprocess.run(
            ["vicinae", "dmenu", "--format", "index", "--placeholder", "Connect to remote PC…",
             "--no-section", "--no-quick-look", "--no-footer", "--width", "640",
             "--height", str(min(500, 70 + 72 * len(entries)))],
            input="\n".join(picker_rows(entries, csv_rows)),
            capture_output=True,
            text=True,
        )
    # Dmenu can also return arbitrary search text. Only accept a valid row index.
    selected = choice.stdout.strip()
    if choice.returncode == 0 and selected.isdecimal() and int(selected) < len(entries):
        command = ["conference-rdp", "--launch"] if args.csv else ["gio", "launch"]
        subprocess.run(command + [entries[int(selected)][1]], check=True)


if __name__ == "__main__":
    main()
