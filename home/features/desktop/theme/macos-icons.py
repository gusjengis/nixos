#!/usr/bin/env python3
"""Build the native theme, or watch installed apps for incremental updates."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import runpy
import shutil
import signal
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parent
builder = runpy.run_path(str(ROOT / "build-macos-theme.py"))
generator = runpy.run_path(str(ROOT / "generate-macos-app-icons.py"))


def refresh(data, *, full=False):
    state = data / "macos-native"
    state.mkdir(parents=True, exist_ok=True)
    theme = data / "icons/MacOS-Native"
    with (state / "update.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if full or not (theme / "index.theme").exists():
            if (ROOT / "icon-source/manifest.json").exists():
                builder["build"](ROOT / "icon-source", theme)
            else:
                builder["write_index"](theme)
        changed = generator["generate"](theme, preserve_library=True)
        if changed or full:
            subprocess.run(["gtk-update-icon-cache", "-f", str(theme)], check=True)
            # Existing IPC reloads icon pixels in place; never replace the
            # launcher process or discard the user's query/navigation state.
            if shutil.which("vicinae"):
                try:
                    result = subprocess.run(["vicinae", "deeplink", "vicinae://theme/refresh-icons"],
                                            capture_output=True, timeout=5)
                    if result.returncode:
                        print("Vicinae icon refresh unavailable; next launch will use current icons", flush=True)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        return changed


def watch(data):
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    pending, stopped = threading.Event(), threading.Event()
    output = data / "icons/MacOS-Native"
    output_paths = (output, output.resolve())

    class Changes(FileSystemEventHandler):
        def on_any_event(self, event):
            if event.event_type not in ("created", "modified", "deleted", "moved"):
                return
            paths = [Path(event.src_path)]
            if getattr(event, "dest_path", ""):
                paths.append(Path(event.dest_path))
            if any(not any(path == root or root in path.parents for root in output_paths) for path in paths):
                pending.set()

    def stop(*_):
        stopped.set()
        pending.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    observer = Observer()
    handler = Changes()
    watched = {}
    for directory in (data / "applications", data / "icons", data / "pixmaps"):
        directory.mkdir(parents=True, exist_ok=True)

    def add_watches():
        candidates = [(data / name, True) for name in ("applications", "icons", "pixmaps")]
        candidates += [(data / "flatpak/exports/share", True), (Path("/var/lib/flatpak/exports/share"), True),
                       (Path.home() / ".local/state/nix/profiles", False),
                       (Path.home() / ".local/state/nix", False), (Path("/nix/var/nix/profiles"), False)]
        manifest = output / "generated-apps.json"
        if manifest.is_file():
            for entry in json.loads(manifest.read_text()):
                for field in ("source", "desktop"):
                    source = Path(entry[field]).resolve()
                    if not source.is_relative_to("/nix/store"):
                        candidates.append((source.parent, False))
        for path, recursive in candidates:
            if any(parent == path or (recursive_parent and parent in path.parents)
                   for parent, recursive_parent in watched.items()) or not path.is_dir():
                continue
            try:
                observer.schedule(handler, str(path), recursive=recursive)
                watched[path] = recursive
            except OSError as error:
                print(f"Icon watch unavailable for {path}: {error}", flush=True)

    add_watches()
    observer.start()
    try:
        refresh(data)
        add_watches()
        print("Watching installed launchers and source artwork; native output excluded", flush=True)
        while not stopped.is_set():
            # Also reconcile immutable profile changes and newly created export
            # directories that weren't present when the service started.
            pending.wait(60)
            if stopped.is_set():
                break
            while pending.is_set() and not stopped.is_set():
                pending.clear()
                time.sleep(1.5)
            if stopped.is_set():
                break
            try:
                add_watches()
                refresh(data)
                add_watches()
            except Exception as error:
                print(f"Icon refresh failed; will retry: {error}", flush=True)
    finally:
        observer.stop()
        observer.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    if args.watch:
        watch(data)
    else:
        refresh(data, full=True)


if __name__ == "__main__":
    main()
