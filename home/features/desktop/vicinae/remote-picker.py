"""Present configured RDP desktop entries using Vicinae's existing glass UI."""

import configparser
import argparse
import json
from pathlib import Path
import subprocess
import sys


def remotes(manifest):
    entries = []
    for path in manifest:
        desktop = configparser.ConfigParser(interpolation=None, strict=False)
        desktop.read(path)
        if desktop.has_section("Desktop Entry"):
            entries.append((desktop["Desktop Entry"]["Name"], path))
    return sorted(entries)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", nargs="?")
    parser.add_argument("--csv", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.csv:
        listed = subprocess.run(["conference-rdp", "--list"], check=True, capture_output=True, text=True)
        entries = sorted((row["name"], row["name"]) for row in json.loads(listed.stdout))
    else:
        with open(args.manifest) as source:
            entries = remotes(json.load(source))
    if args.list:
        print(json.dumps(entries))
        return

    if subprocess.run(["vicinae", "state", "open"], capture_output=True).returncode == 0:
        subprocess.run(["vicinae", "close"], check=True)
        return
    if not entries:
        return

    choice = subprocess.run(
        ["vicinae", "dmenu", "--format", "index", "--placeholder", "Connect to remote PC…",
         "--no-section", "--no-quick-look", "--no-footer", "--width", "640",
         "--height", str(min(500, 104 + 72 * len(entries)))],
        input="\n".join(f"{name}\t{Path(__file__).with_name('windows-tile.svg')}" for name, _ in entries),
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
