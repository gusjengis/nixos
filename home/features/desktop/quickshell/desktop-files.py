"""Small filesystem boundary for the context desktop. Paths are never shell code."""

import argparse
import configparser
import json
import mimetypes
import os
from pathlib import Path
import subprocess
import sys


def entries(directory):
    result = []
    theme = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "icons/MacOS-Native/128x128"
    for path in directory.iterdir():
        if path.name.startswith("."):
            continue
        try:
            folder = path.is_dir()
            stat = path.stat()
        except OSError:
            folder, stat = False, None  # Broken links still belong on the desktop.
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        icon = "folder" if folder else mime.replace("/", "-")
        display_name = path.name
        app_icon = ""
        if not folder and path.suffix == ".desktop":
            entry = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                entry.read(path, encoding="utf-8")
                display_name = entry.get("Desktop Entry", "Name", fallback=path.name)
                app_icon = entry.get("Desktop Entry", "Icon", fallback="")
            except (OSError, UnicodeError, configparser.Error):
                pass
        image = theme / ("places" if folder else "mimetypes") / (icon + ".png")
        if app_icon and "/" not in app_icon:
            app_image = theme / "apps" / (app_icon.removesuffix(".png") + ".png")
            if app_image.is_file():
                image = app_image
        if not image.is_file():
            image = theme / "mimetypes/application-octet-stream.png"
        result.append({"name": path.name, "displayName": display_name, "url": path.as_uri(), "folder": folder,
                       "icon": icon, "iconUrl": image.as_uri() if image.is_file() else "",
                       "modified": stat.st_mtime if stat else 0,
                       "size": stat.st_size if stat else 0})
    return sorted(result, key=lambda entry: entry["name"].casefold())


def new_folder(directory):
    for number in range(1, 10001):
        path = directory / ("untitled folder" if number == 1 else f"untitled folder {number}")
        try:
            path.mkdir()
            return path.name
        except FileExistsError:
            continue
    raise ValueError("Too many untitled folders")


def child(directory, name):
    # Keep mutations at the desktop root; do not resolve symlinks before trashing.
    if not name or name.startswith(".") or Path(name).name != name or "\x00" in name:
        raise ValueError("Expected a visible desktop filename")
    return directory / name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["list", "new-folder", "open", "trash"])
    parser.add_argument("directory", type=Path)
    parser.add_argument("names", nargs="*")
    args = parser.parse_args()
    directory = args.directory.absolute()
    if not directory.is_dir():
        raise ValueError("Context folder unavailable")
    if args.action == "list":
        print(json.dumps(entries(directory)))
    elif args.action == "new-folder":
        print(json.dumps({"created": new_folder(directory)}))
    else:
        paths = [child(directory, name) for name in args.names]
        if args.action == "trash":
            if paths:
                subprocess.run(["gio", "trash", "--", *map(str, paths)], check=True)
        else:
            for path in paths or [directory]:
                # Launch shortcuts only after an explicit user Open action.
                operation = "launch" if path.suffix == ".desktop" and not path.is_dir() else "open"
                subprocess.run(["gio", operation, str(path) if operation == "launch" else path.as_uri()], check=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
