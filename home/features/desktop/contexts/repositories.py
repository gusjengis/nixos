#!/usr/bin/env python3
"""Explicit checkout registry and conservative, machine-local Syncthing excludes.

Nested contexts inside a checkout cannot be discovered without walking checkout
contents. Context creation must check that invariant before registering a parent.
Legacy working_directory is deliberately not interpreted as a registration.
"""

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


INCLUDE_FILE = ".context-repositories.stignore"
LEDGER_FILE = ".context-repositories.json"
INCLUDE = f"#include {INCLUDE_FILE}"
STATIC_BASE = [INCLUDE, INCLUDE_FILE, LEDGER_FILE, "**/.git"]


class RepositoryError(Exception):
    """Unsafe registry, exclusion state, or unavailable live protection."""


def _relative(value):
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(part in ("", ".", "..") or part.startswith(".")
                   for part in value.split("/"))
            or any(unicodedata.category(char) in ("Cc", "Cs") for char in value)):
        raise RepositoryError("Invalid repository relative path")
    return Path(value)


def _contained(base, path):
    try:
        resolved = path.resolve()
        if not resolved.is_relative_to(base.resolve()):
            raise RepositoryError("Repository path escapes context")
        return resolved
    except (OSError, RuntimeError):
        raise RepositoryError("Cannot resolve repository path") from None


def repository_paths(directory: Path, data: dict) -> list[Path]:
    """Validate v1 registrations; return absolute lexical checkout paths.

    Hidden segments (including .context and .git) are not registrations. Missing
    checkouts are valid. Both lexical and resolved overlaps are forbidden.
    """
    directory = directory.absolute()
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise RepositoryError("Invalid context metadata version")
    records = data.get("repositories", [])
    if not isinstance(records, list):
        raise RepositoryError("Invalid repository registrations")
    paths, targets = [], []
    for record in records:
        if (not isinstance(record, dict) or "path" not in record
                or ("url" in record and not isinstance(record["url"], str))):
            raise RepositoryError("Invalid repository registration")
        path = directory / _relative(record["path"])
        target = _contained(directory, path)
        if target == directory.resolve():
            raise RepositoryError("Repository resolves to context itself")
        _relative(target.relative_to(directory.resolve()).as_posix())
        for previous, resolved in zip(paths, targets):
            if (path.is_relative_to(previous) or previous.is_relative_to(path)
                    or target.is_relative_to(resolved) or resolved.is_relative_to(target)):
                raise RepositoryError("Overlapping repository registrations")
        # Check only path ancestors, never recurse into a checkout.
        for ancestor in (path, *path.parents):
            if ancestor == directory:
                break
            if (ancestor / ".context").exists():
                raise RepositoryError("Repository conflicts with nested context")
        paths.append(path)
        targets.append(target)
    return paths


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Never include metadata, URLs, API keys, or parser input in errors.
        raise RepositoryError("Cannot read repository metadata or ledger") from None


def registered(root: Path) -> list[dict]:
    """List {context: Path, path: Path, url?: str}, without visiting checkouts."""
    result = []
    for directory, data, paths in _walk_contexts(root):
        for record, path in zip(data.get("repositories", []), paths):
            item = {"context": directory, "path": path}
            if "url" in record:
                item["url"] = record["url"]
            result.append(item)
    return result


def _walk_contexts(root):
    root = root.resolve()
    pruned = set()
    if not root.exists():
        return

    def failed(_error):
        raise RepositoryError("Cannot walk context tree")

    for name, children, files in os.walk(root, followlinks=False, onerror=failed):
        directory = Path(name)
        if ".context" in children or ".context" in files:
            metadata = directory / ".context/context.json"
            _contained(directory, metadata)
            data = _read(metadata)
            paths = repository_paths(directory, data)
            pruned.update(paths)
            pruned.update(path.resolve() for path in paths)
            yield directory, data, paths
        children[:] = sorted(child for child in children
                             if not child.startswith(".")
                             and not (directory / child).is_symlink()
                             and directory / child not in pruned)


@contextmanager
def _lock(root, kind):
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "desktop-contexts"
    state.mkdir(parents=True, exist_ok=True)
    scope = hashlib.sha256(os.fsencode(root.resolve())).hexdigest()
    with (state / f"repositories-{scope}-{kind}.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def _atomic(path, text):
    if path.is_symlink():
        raise RepositoryError("Refusing symlink for local repository state")
    if path.exists() and path.read_bytes() == text.encode("utf-8"):
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".context-repositories-", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def owning_context(root: Path, destination: Path) -> Path | None:
    """Nearest registered-context ancestor; resolve cwd/parent symlinks first."""
    root, destination = root.resolve(), destination.resolve()
    if not destination.is_relative_to(root):
        return None
    contexts = list(_walk_contexts(root))
    if any(destination == directory for directory, _, _ in contexts):
        raise RepositoryError("Destination is a context directory")
    owners = [directory for directory, _, _ in contexts if destination.is_relative_to(directory)]
    return max(owners, key=lambda path: len(path.parts), default=None)


def register(root: Path, context: Path, destination: Path, url: str | None = None) -> None:
    """Atomically add/update one record, preserving all other metadata."""
    root, context, destination = root.resolve(), context.resolve(), destination.resolve()
    if url is not None and not isinstance(url, str):
        raise RepositoryError("Repository URL must be a string")
    with _lock(root, "register"):
        owner = owning_context(root, destination)
        if owner != context:
            raise RepositoryError("Destination does not belong to context")
        contexts = list(_walk_contexts(root))
        if any(directory.is_relative_to(destination) for directory, _, _ in contexts):
            raise RepositoryError("Repository encloses a context")
        for item in registered(root):
            if item["path"].resolve() != destination and destination.is_relative_to(item["path"].resolve()):
                raise RepositoryError("Destination lies inside registered checkout")
        metadata = context / ".context/context.json"
        data = _read(metadata)
        relative = destination.relative_to(context).as_posix()
        records = data.setdefault("repositories", [])
        repository_paths(context, data)
        for record in records:
            if (context / record["path"]).resolve() == destination:
                if url is not None:
                    record["url"] = url
                break
        else:
            record = {"path": relative}
            if url is not None:
                record["url"] = url
            records.append(record)
        repository_paths(context, data)
        _atomic(metadata, json.dumps(data, ensure_ascii=True, indent=2) + "\n")


def _pattern(relative):
    _relative(relative)
    # Syncthing uses gobwas/glob; slash rooting prevents !/#/(?i) prefixes.
    return "/" + "".join("\\" + char if char in "\\*?[]{}," else char for char in relative)


def _live(root, patterns):
    try:
        config = Path(os.environ.get("SYNCTHING_CONFIG", Path.home() / ".config/syncthing/config.xml"))
        key = ET.parse(config).getroot().findtext("gui/apikey")
        if not key:
            raise RepositoryError("Syncthing API key unavailable")
        base = os.environ.get("SYNCTHING_URL", "http://127.0.0.1:8384").rstrip("/")
        endpoint = base + "/rest/db/ignores?" + urllib.parse.urlencode({"folder": "sessions"})

        def request(value=None, *, endpoint=endpoint):
            body = None if value is None else json.dumps(value).encode("utf-8")
            req = urllib.request.Request(endpoint, data=body,
                                         headers={"X-API-Key": key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as response:
                result = json.load(response)
            if not isinstance(result, dict) or result.get("error"):
                raise RepositoryError("Syncthing ignore response invalid")
            return result

        folder = request(endpoint=base + "/rest/config/folders/sessions")
        folder_path = folder.get("path")
        if not isinstance(folder_path, str) or not folder_path:
            raise RepositoryError("Syncthing folder path missing")
        folder_path = Path(folder_path).expanduser()
        if not folder_path.is_absolute() or folder_path.resolve() != root.resolve():
            raise RepositoryError("Syncthing folder root mismatch")

        current = request()
        if "ignore" not in current:
            raise RepositoryError("Syncthing ignore list missing")
        ignores = current.get("ignore")
        if ignores is None:
            ignores = []
        if not isinstance(ignores, list) or not all(isinstance(line, str) for line in ignores):
            raise RepositoryError("Syncthing ignore list invalid")
        # Own only this directive. Preserve every unrelated line and its order.
        ignores = [INCLUDE] + [line for line in ignores if line.strip() != INCLUDE]
        expected = [pattern for base_pattern in patterns for pattern in (base_pattern, base_pattern + "/**")]
        expanded = current.get("expanded")
        if (current.get("ignore") == ignores and isinstance(expanded, list)
                and expanded[:len(expected)] == expected):
            return
        request({"ignore": ignores})  # Reload stale expansions as well as changed lines.
        confirmed = request()
        expanded = confirmed.get("expanded")
        if (confirmed.get("ignore") != ignores or not isinstance(expanded, list)
                or expanded[:len(expected)] != expected):
            raise RepositoryError("Syncthing live exclusions not confirmed")
    except Exception:
        # urllib/XML errors may contain credentials; expose only fixed text.
        raise RepositoryError("Syncthing live exclusions not confirmed") from None


def sync(root: Path, *, require_live: bool = False) -> dict:
    """Union current and historical root-relative checkouts; confirm REST state.

    Offline generation is available through CLI --offline. Python callers always
    attempt REST; failures return live=False unless require_live=True.
    """
    return _sync(root, require_live=require_live, offline=False)


def _sync(root, *, require_live=False, offline=False):
    root = root.resolve()
    with _lock(root, "sync"):
        # Syncthing does not follow directory symlinks, but their physical targets
        # remain syncable through ordinary paths in the same context.
        current = {path.relative_to(root).as_posix() for item in registered(root)
                   for path in (item["path"], item["path"].resolve())}
        ledger = root / LEDGER_FILE
        previous = set()
        if ledger.exists() or ledger.is_symlink():
            if ledger.is_symlink():
                raise RepositoryError("Refusing symlink ledger")
            data = _read(ledger)
            if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1
                    or not isinstance(data.get("paths"), list)):
                raise RepositoryError("Invalid repository exclusion ledger")
            for value in data["paths"]:
                _relative(value)
                previous.add(value)
        elif (root / INCLUDE_FILE).exists():
            raise RepositoryError("Generated exclusions exist without ledger")
        paths = sorted(current | previous)
        patterns = [_pattern(path) for path in paths]
        root.mkdir(parents=True, exist_ok=True)
        # Persist union first: interruption can only retain extra exclusions.
        _atomic(ledger, json.dumps({"version": 1, "paths": paths}, ensure_ascii=True, indent=2) + "\n")
        _atomic(root / INCLUDE_FILE, "#escape=\\\n" + "\n".join(patterns) + "\n")
        live = False
        if not offline:
            try:
                _live(root, patterns)
                live = True
            except RepositoryError:
                if require_live:
                    raise
        return {"paths": paths, "live": live}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("sync", "watch"):
        subparser = commands.add_parser(command)
        subparser.add_argument("--root", type=Path, default=Path.home() / "sessions")
        if command == "sync":
            mode = subparser.add_mutually_exclusive_group()
            mode.add_argument("--offline", action="store_true")
            mode.add_argument("--require-live", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "sync":
        try:
            result = _sync(args.root, require_live=args.require_live, offline=args.offline)
            print(json.dumps(result))
            return 0
        except (RepositoryError, OSError):
            print("repositories: exclusion sync failed; prior exclusions retained", file=sys.stderr)
            return 1
    while True:
        try:
            sync(args.root, require_live=True)
        except (RepositoryError, OSError):
            print("repositories: exclusion sync failed; retrying", file=sys.stderr)
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
