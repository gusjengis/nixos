#!/usr/bin/env python3
"""Identify game windows whose WM_CLASS does not name a desktop entry.

Proton windows are classed `steam_app_<SteamGameId>`, which is 0 for games
started outside Steam. Launchers export GIO_LAUNCHED_DESKTOP_FILE, which the
window process inherits; Steam games fall back to their library manifest.

Usage: dock-identity.py [--pid PID]... [--steam APPID]...
Prints {"pids": {pid: desktop-id}, "steam": {appid: {"name", "icon"}}}.
"""

import argparse
import json
import os
import re
from pathlib import Path

STEAM = Path(os.environ.get("HOME", "~")).expanduser() / ".local/share/Steam"


def desktop_id(path):
    # Desktop entry IDs are paths below an applications directory, with
    # subdirectory separators replaced by dashes.
    path = path.strip()
    if not path.endswith(".desktop"):
        return ""
    _, marker, relative = path.rpartition("/applications/")
    return (relative if marker else os.path.basename(path))[: -len(".desktop")].replace("/", "-")


def launched_entry(pid):
    try:
        environ = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return ""
    for item in environ.split(b"\0"):
        if item.startswith(b"GIO_LAUNCHED_DESKTOP_FILE="):
            return desktop_id(item.split(b"=", 1)[1].decode(errors="replace"))
    return ""


def libraries(steam=STEAM):
    found = [steam]
    try:
        text = (steam / "steamapps/libraryfolders.vdf").read_text(errors="replace")
    except OSError:
        return found
    for value in re.findall(r'^\s*"path"\s*"([^"]*)"', text, re.M):
        library = Path(value.replace("\\\\", "\\"))
        if library not in found:
            found.append(library)
    return found


def steam_game(appid, steam=STEAM):
    name = ""
    for library in libraries(steam):
        try:
            text = (library / f"steamapps/appmanifest_{appid}.acf").read_text(errors="replace")
        except OSError:
            continue
        match = re.search(r'^\s*"name"\s*"([^"]*)"', text, re.M)
        if match:
            name = match.group(1)
            break
    # The hash-named image is Steam's square client icon; other files are
    # banners and capsules.
    icon = ""
    cache = steam / "appcache/librarycache" / appid
    try:
        icons = sorted(p for p in cache.iterdir() if re.fullmatch(r"[0-9a-f]{40}\.(?:jpg|png|ico)", p.name))
        if icons:
            icon = "file://" + str(icons[0])
    except OSError:
        pass
    return {"name": name, "icon": icon}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", action="append", default=[])
    parser.add_argument("--steam", action="append", default=[])
    args = parser.parse_args()
    result = {
        "pids": {pid: launched_entry(pid) for pid in args.pid if pid.isdigit()},
        "steam": {appid: steam_game(appid) for appid in args.steam if appid.isdigit() and appid != "0"},
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
