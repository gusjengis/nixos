#!/usr/bin/env python3
"""Flatten legacy checkouts. Pause sessions on every peer before --prepare;
deploy exact-exclusion services before --apply. Default is read-only planning.
"""

import argparse
import errno
import json
import os
from pathlib import Path
import sys
import uuid

import contextctl
import repositories as exclusions


RECOVERY = (
    "Keep sessions paused on all peers. Inspect source, target, metadata and listed symlinks. "
    "If only target exists, rename target back to source (same filesystem, never overwrite). "
    "Restore working_directory to source relative to context; retain BOTH repository registrations. "
    "Restore listed symlinks only if they still point exactly to target. "
    "After verifying rollback, mark journal record failed, then rerun --prepare and --apply. "
    "Never remove historical exclusion ledger paths."
)


def journal_path():
    return contextctl.state_root() / "flatten-migration.json"


def read_journal():
    data = contextctl.read_json(journal_path(), {"version": 1, "records": []})
    if (not isinstance(data, dict) or data.get("version") != 1
            or not isinstance(data.get("records"), list)
            or any(not isinstance(record, dict)
                   or any(not isinstance(record.get(key), str)
                          for key in ("source", "target", "uuid", "status"))
                   for record in data["records"])):
        raise ValueError("Invalid flatten journal; refusing to overwrite")
    for record in data["records"]:
        if record["status"] not in ("prepared", "moved", "failed"):
            raise ValueError(f"Interrupted flatten transaction: {record['source']}. {RECOVERY}")
    return data


def check_directory(path):
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ValueError(f"Symlink in directory path: {ancestor}")
        if ancestor.exists() and (not ancestor.is_dir() or os.path.lexists(ancestor / ".git")):
            raise ValueError(f"Not a plain directory outside Git: {ancestor}")


def prepared_metadata(data, old, new):
    records = [dict(record) for record in data.get("repositories", [])]
    source = next((record for record in records if record["path"] == old), {"path": old})
    target = next((record for record in records if record["path"] == new), {"path": new})
    if any(key != "path" and key in target and target[key] != value for key, value in source.items()):
        raise ValueError("Old and flat repository metadata conflict")
    merged = dict(source, **target)
    if not any(record["path"] == old for record in records):
        records.append(source)
    records = [merged if record["path"] == new else record for record in records]
    if not any(record["path"] == new for record in records):
        records.append(merged)
    return dict(data, repositories=records)


def plan():
    """Never use scan(): unregistered legacy repos must not be traversed."""
    root = contextctl.root()
    check_directory(root)
    entries, seen, pruned = [], set(), set()

    def failed(error):
        raise error

    for name, children, files in os.walk(root, followlinks=False, onerror=failed):
        directory = Path(name)
        if ".context" in children or ".context" in files:
            check_directory(directory / ".context")
            metadata = directory / ".context/context.json"
            if metadata.is_symlink():
                raise ValueError(f"Symlink metadata: {metadata}")
            data = contextctl.read_json(metadata)
            paths = exclusions.repository_paths(directory, data)
            pruned.update(paths)
            identifier = str(uuid.UUID(data["id"]))
            if identifier != data["id"] or identifier in seen or data.get("name") != directory.name:
                raise ValueError(f"Invalid or duplicate context identity: {metadata}")
            seen.add(identifier)
            notes = directory / ".context/notes"
            if not (notes / ".obsidian").is_dir():
                raise ValueError(f"Incomplete note vault: {notes}")
            cwd = data.get("working_directory")
            contextctl.working_path(directory, cwd)
            parts = cwd.split("/")
            if len(parts) == 2 and parts[0] == "work":
                contextctl.relative_name(parts[1], leaf=True)
                source, target = directory / cwd, directory / parts[1]
                entry = {"source": str(source), "target": str(target), "uuid": identifier,
                         "context": str(directory), "name": directory.relative_to(root).as_posix(),
                         "status": "ready", "reason": ""}
                entries.append(entry)
                try:
                    check_directory(source.parent)
                    if source.is_symlink():
                        raise ValueError("Legacy checkout is a symlink")
                    if os.path.lexists(target):
                        raise ValueError("Flat target already exists; never overwrite")
                    if not source.is_dir():
                        raise ValueError("Legacy checkout missing; inspect flatten journal for recovery")
                    marker = source / ".git"
                    if marker.is_file() or marker.is_symlink():
                        entry.update(status="skipped", reason=".git file/symlink: linked worktree or submodule")
                    elif not marker.is_dir():
                        raise ValueError("Legacy checkout has no .git directory")
                    if source.stat().st_dev != directory.stat().st_dev or source.stat().st_dev != source.parent.stat().st_dev:
                        raise ValueError("Move is not a same-filesystem rename")
                    candidate = prepared_metadata(data, cwd, parts[1])
                    exclusions.repository_paths(directory, candidate)
                except (OSError, ValueError, contextctl.ContextError, exclusions.RepositoryError) as error:
                    entry.update(status="conflict", reason=str(error))
        children[:] = sorted(child for child in children
                             if child != "work" and not child.startswith(".")
                             and directory / child not in pruned
                             and not (directory / child).is_symlink())
    return entries


def legacy_links(entries):
    original = contextctl.read_json(contextctl.state_root() / "repo-migration.json",
                                    {"version": 1, "records": []})
    if (not isinstance(original, dict) or original.get("version") != 1
            or not isinstance(original.get("records"), list)
            or any(not isinstance(record, dict) or any(not isinstance(record.get(key), str)
                       for key in ("source", "target", "uuid")) for record in original["records"])):
        raise ValueError("Invalid original migration journal")
    code = Path.home() / "Documents/Code"
    for entry in entries:
        links = []
        for record in original["records"]:
            link = Path(record["source"])
            if (record["uuid"] == entry["uuid"] and record["target"] == entry["source"]
                    and link.is_absolute() and link.is_relative_to(code) and ".." not in link.parts
                    and link.is_symlink() and os.readlink(link) == entry["source"]):
                check_directory(link.parent)
                links.append(str(link))
        entry["symlinks"] = sorted(set(links))


def metadata_for(entry):
    directory = Path(entry["context"])
    path = directory / ".context/context.json"
    data = contextctl.read_json(path)
    if data.get("id") != entry["uuid"] or data.get("working_directory") != f"work/{Path(entry['source']).name}":
        raise ValueError("Context changed after preflight")
    exclusions.repository_paths(directory, data)
    return path, data


def prepare(entries, journal):
    for entry in entries:
        if entry["status"] != "ready":
            continue
        path, data = metadata_for(entry)
        data = prepared_metadata(data, f"work/{Path(entry['source']).name}", Path(entry["target"]).name)
        exclusions.repository_paths(Path(entry["context"]), data)
        record = next((item for item in journal["records"] if all(item[key] == entry[key]
                       for key in ("source", "target", "uuid"))), None)
        if record is None:
            record = {key: entry[key] for key in ("source", "target", "uuid")}
            journal["records"].append(record)
        record.update(status="prepared", symlinks=entry["symlinks"], recovery=RECOVERY)
        contextctl.atomic_json(journal_path(), journal)
        if contextctl.read_json(path) != data:
            contextctl.atomic_json(path, data)
        entry["status"] = "prepared"


def replace_link(link, expected, target):
    if not link.is_symlink() or os.readlink(link) != expected:
        raise ValueError(f"Symlink changed after preflight: {link}")
    temporary = link.with_name(f".flatten-{uuid.uuid4()}")
    try:
        temporary.symlink_to(target, target_is_directory=True)
        os.replace(temporary, link)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def apply(entries, journal):
    ready = [entry for entry in entries if entry["status"] == "ready"]
    if not ready:
        return
    # Validate the entire batch before contacting REST or moving any checkout.
    for entry in ready:
        _, data = metadata_for(entry)
        required = {f"work/{Path(entry['source']).name}", Path(entry["target"]).name}
        if not required.issubset({record["path"] for record in data.get("repositories", [])}):
            raise ValueError("Run --prepare with sessions paused on every peer before --apply")
        if not any(record["status"] == "prepared" and all(record[key] == entry[key]
                   for key in ("source", "target", "uuid")) for record in journal["records"]):
            raise ValueError("Missing prepared flatten journal; run --prepare first")
    if not exclusions.sync(contextctl.root(), require_live=True).get("live"):
        raise exclusions.RepositoryError("Syncthing live exclusions not confirmed")
    for entry in ready:
        source, target = Path(entry["source"]), Path(entry["target"])
        path, before = metadata_for(entry)
        check_directory(source.parent)
        if source.is_symlink() or not (source / ".git").is_dir() or (source / ".git").is_symlink():
            raise ValueError("Source changed after preflight")
        if os.path.lexists(target):
            raise ValueError("Target appeared after preflight; never overwrite")
        record = next(item for item in journal["records"] if all(item[key] == entry[key]
                      for key in ("source", "target", "uuid")))
        record.update(status="moving", symlinks=entry["symlinks"], recovery=RECOVERY)
        contextctl.atomic_json(journal_path(), journal)
        moved, changed_links = False, []
        try:
            source.rename(target)
            moved = True
            for name in entry["symlinks"]:
                link = Path(name)
                replace_link(link, str(source), str(target))
                changed_links.append(link)
            merged = prepared_metadata(before, f"work/{source.name}", target.name)
            after = dict(merged, working_directory=target.name,
                         repositories=[item for item in merged["repositories"]
                                       if item["path"] != f"work/{source.name}"])
            contextctl.atomic_json(path, after)
            record["status"] = "moved"
            contextctl.atomic_json(journal_path(), journal)
        except (OSError, ValueError, contextctl.ContextError) as error:
            record.update(status="failed", error=str(error))
            try:
                if moved:
                    if os.path.lexists(source):
                        raise ValueError("Source occupied; cannot roll back")
                    target.rename(source)
                for link in reversed(changed_links):
                    replace_link(link, str(target), str(source))
                contextctl.atomic_json(path, before)
            except (OSError, ValueError, contextctl.ContextError) as rollback_error:
                record.update(status="recovery-required", rollback_error=str(rollback_error))
            try:
                contextctl.atomic_json(journal_path(), journal)
            except OSError:
                pass  # Persisted moving record already contains recovery instructions.
            raise ValueError(f"Flatten failed: {error}. Journal: {journal_path()}. {RECOVERY}") from error
        entry["status"] = "moved"
        try:
            source.parent.rmdir()
        except OSError as error:
            if error.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                entry["reason"] = f"Checkout moved; could not remove empty work directory: {error}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Override CONTEXT_ROOT")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--prepare", action="store_true", help="Register old AND flat paths; do not move")
    mode.add_argument("--apply", action="store_true", help="Require prepared paths and live exclusions, then rename")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.root is not None:
        os.environ["CONTEXT_ROOT"] = str(args.root.absolute())
    try:
        def run():
            entries, journal = plan(), read_journal()
            legacy_links(entries)
            if not any(entry["status"] == "conflict" for entry in entries):
                if args.prepare:
                    prepare(entries, journal)
                elif args.apply:
                    apply(entries, journal)
            return entries

        if args.prepare or args.apply:
            with contextctl.mutation_lock():
                entries = run()
        else:
            entries = run()
        report = {"prepare": args.prepare, "apply": args.apply,
                  "root": str(contextctl.root()), "journal": str(journal_path()), "entries": entries}
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("PREPARE" if args.prepare else "APPLY" if args.apply else "DRY RUN (no changes)")
            for entry in entries:
                print(f"{entry['status']}: {entry['uuid']} {entry['source']} -> {entry['target']} {entry['reason']}")
        return int(any(entry["status"] == "conflict" for entry in entries))
    except (OSError, ValueError, KeyError, TypeError, AttributeError,
            contextctl.ContextError, exclusions.RepositoryError) as error:
        if args.json:
            print(json.dumps({"error": str(error), "journal": str(journal_path())}))
        else:
            print(f"flatten-repos: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
