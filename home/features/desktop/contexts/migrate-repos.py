#!/usr/bin/env python3
"""Plan repository relocation without changes; use --apply after reviewing the report."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import stat
import sys

import contextctl
import repositories as exclusions


def check_directory(path):
    """Reject redirected paths and directories inside Git, including metadata."""
    if ".." in path.parts:
        raise ValueError(f"Parent traversal is not allowed: {path}")
    for parent in reversed((path, *path.parents)):
        if parent.name == ".git":
            raise ValueError(f"Path is inside Git metadata: {path}")
        if parent.is_symlink():
            raise ValueError(f"Symlink in directory path: {parent}")
        if parent.exists():
            if not parent.is_dir():
                raise ValueError(f"Not a directory: {parent}")
            if os.path.lexists(parent / ".git"):
                raise ValueError(f"Directory is inside a repository: {parent}")


def repositories(directory):
    for child in sorted(directory.iterdir()):
        if child.name.startswith("."):
            continue
        mode = child.lstat().st_mode
        if stat.S_ISLNK(mode):
            yield child, "symlink"
        elif stat.S_ISDIR(mode):
            marker = child / ".git"
            if os.path.lexists(marker):
                yield child, "repo" if marker.is_dir() and not marker.is_symlink() else "git-file"
            else:
                yield from repositories(child)


def plan(source):
    root = contextctl.root()
    check_directory(source)
    check_directory(root)
    if source.is_relative_to(root) or root.is_relative_to(source):
        raise ValueError("Source and context root must not overlap")
    if not source.is_dir():
        raise ValueError(f"Missing source directory: {source}")
    contexts = {item["name"]: item for item in contextctl.scan()}
    entries = []
    for path, kind in repositories(source):
        name = path.relative_to(source).as_posix()
        directory = root / name
        target = directory / path.name
        entry = {"source": str(path), "target": str(target), "name": name,
                 "uuid": contexts.get(name, {}).get("id"), "status": "ready", "reason": ""}
        entries.append(entry)
        if kind == "symlink":
            entry.update(status="skipped", reason="Source symlink; never traversed")
            try:
                if path.resolve() == target.resolve() and target.is_dir():
                    entry["status"] = "already-migrated"
            except (OSError, RuntimeError):
                pass  # Dangling or cyclic links are not migration candidates.
            continue
        if kind == "git-file":
            entry.update(status="skipped", reason=".git is a file or symlink; worktrees/submodules require special handling")
            continue
        try:
            contextctl.relative_name(name)
            check_directory(target.parent)
            if os.path.lexists(target):
                raise ValueError("Target already exists; will not merge or replace")
            if name in contexts:
                metadata = contextctl.read_json(directory / ".context/context.json")
                if metadata["working_directory"] != path.name:
                    raise ValueError("Existing context has a different working_directory")
            ancestor = target.parent
            while not ancestor.exists():
                ancestor = ancestor.parent
            if path.stat().st_dev != ancestor.stat().st_dev or path.stat().st_dev != path.parent.stat().st_dev:
                raise ValueError("Move is not a same-filesystem rename")
        except (ValueError, OSError, contextctl.ContextError) as exc:
            entry.update(status="conflict", reason=str(exc))
    return entries


def journal_path():
    return contextctl.state_root() / "repo-migration.json"


def read_journal():
    data = contextctl.read_json(journal_path(), {"version": 1, "records": []})
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("records"), list)
            or any(not isinstance(item, dict) or not all(key in item for key in ("source", "target", "uuid"))
                   for item in data["records"])):
        raise ValueError("Invalid migration journal; refusing to overwrite")
    return data


def apply(entries, journal):
    for entry in entries:
        if entry["status"] != "ready":
            continue
        source, target = Path(entry["source"]), Path(entry["target"])
        # Recheck before each move as other programs may have provisioned a clone.
        check_directory(target.parent)
        if source.is_symlink() or not (source / ".git").is_dir() or (source / ".git").is_symlink():
            raise ValueError(f"Source changed after preflight: {source}")
        if os.path.lexists(target):
            raise ValueError(f"Target appeared after preflight: {target}")
        if entry["uuid"] is None:
            entry["uuid"] = contextctl.create(entry["name"], source.name)["id"]
        target.parent.mkdir(parents=True, exist_ok=True)
        exclusions.register(contextctl.root(), target.parent, target)
        if not exclusions.sync(contextctl.root(), require_live=True).get("live"):
            raise exclusions.RepositoryError("Syncthing live exclusions not confirmed")
        record = {key: entry[key] for key in ("source", "target", "uuid")}
        record["status"] = "prepared"
        journal["records"].append(record)
        contextctl.atomic_json(journal_path(), journal)
        moved = False
        try:
            # Never copy across filesystems: rename preserves dirty/untracked data and inodes.
            source.rename(target)
            moved = True
            source.symlink_to(target, target_is_directory=True)
        except OSError as exc:
            if moved and not os.path.lexists(source):
                target.rename(source)
            record.update(status="failed", error=str(exc))
            contextctl.atomic_json(journal_path(), journal)
            raise
        record["status"] = "moved"
        contextctl.atomic_json(journal_path(), journal)
        entry["status"] = "moved"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.home() / "Documents/Code")
    parser.add_argument("--root", type=Path, help="Override CONTEXT_ROOT")
    parser.add_argument("--apply", action="store_true", help="Move ready repos; conflicts remain untouched")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable report")
    args = parser.parse_args(argv)
    if args.root is not None:
        os.environ["CONTEXT_ROOT"] = str(args.root.absolute())
    source = args.source.absolute()
    try:
        entries = plan(source)
        journal = read_journal()
        if args.apply:
            contextctl.state_root().mkdir(parents=True, exist_ok=True)
            with (contextctl.state_root() / "repo-migration.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                entries, journal = plan(source), read_journal()
                apply(entries, journal)
        report = {"apply": args.apply, "source": str(source), "root": str(contextctl.root()), "entries": entries}
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("APPLY" if args.apply else "DRY RUN (no changes)")
            for entry in entries:
                print(f"{entry['status']}: {entry['source']} -> {entry['target']}"
                      + (f" ({entry['reason']})" if entry["reason"] else ""))
            print(f"{len(entries)} entries; {sum(item['status'] == 'conflict' for item in entries)} conflicts")
        return 1 if any(item["status"] == "conflict" for item in entries) else 0
    except (OSError, ValueError, contextctl.ContextError, exclusions.RepositoryError) as exc:
        if args.json:
            print(json.dumps({"apply": args.apply, "error": str(exc)}))
        else:
            print(f"migrate-repos: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
