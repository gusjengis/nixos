"""Manually close any thought as dealt-with, or reopen it as todo.

Accepts a title or vault-relative Thoughts/path.md. Body bytes are retained;
frontmatter is reserialized with PyYAML. Reopening clears closure metadata.
The default .note-extract.lock inside the vault coordinates local CLI writers
only. On an extraction host, pass --lock /var/lib/note-extract/lock; all writers
must use the same lock. Locks do not coordinate Obsidian or remote sync edits.
"""

import argparse
import datetime
import fcntl
import os
import re
import stat
import tempfile
from pathlib import Path

import yaml


def _no_timestamps(cls):
    # Dates remain strings and round-trip without normalization or quoting.
    cls.yaml_implicit_resolvers = {
        first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    return cls


@_no_timestamps
class Loader(yaml.SafeLoader):
    pass


@_no_timestamps
class Dumper(yaml.SafeDumper):
    pass


def change_status(vault: Path, thought: str, *, reopen=False, reason=None,
                  resolution=None, evidence=(), lock=None) -> Path:
    vault = vault.resolve(strict=True)
    relative = Path(thought)
    if (not thought.strip() or not relative.parts or relative.is_absolute()
            or ".." in relative.parts):
        raise ValueError("thought must be a safe relative Thoughts path or title")
    if relative.parts[0] != "Thoughts":
        if len(relative.parts) != 1:
            raise ValueError("paths must start with Thoughts/")
        relative = Path("Thoughts") / relative
    if relative.suffix != ".md":
        relative = Path(str(relative) + ".md")
    path = vault / relative
    if reopen and (reason is not None or resolution is not None or evidence):
        raise ValueError("--reopen cannot include closure reason, resolution or evidence")
    lock_path = Path(lock) if lock is not None else vault / ".note-extract.lock"
    if lock_path.resolve() == path or lock_path.is_symlink():
        raise ValueError("lock must be a separate, non-symlink file")
    with lock_path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        if any(p.is_symlink() for p in [path, *path.parents] if vault in p.parents):
            raise ValueError("symlinked Thoughts paths are not allowed")
        path.resolve(strict=True).relative_to(vault / "Thoughts")
        if not path.is_file():
            raise ValueError("thought must be an existing Markdown file")
        original = path.read_bytes()
        match = re.match(rb"\A---\r?\n(.*?)^---(?:\r?\n|\Z)", original, re.DOTALL | re.MULTILINE)
        if match is None:
            raise ValueError("thought requires valid YAML frontmatter")
        meta = yaml.load(match.group(1).decode("utf-8"), Loader=Loader)
        if not isinstance(meta, dict):
            raise ValueError("frontmatter must be a mapping")  # noqa: TRY004 - Invalid note input.
        meta["status"] = "todo" if reopen else "dealt-with"
        meta["status-source"] = "manual"
        meta["status-at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        for key in ("status-reason", "resolution", "evidence"):
            meta.pop(key, None)
        if not reopen:
            if reason is not None:
                meta["status-reason"] = reason
            if resolution is not None:
                meta["resolution"] = resolution
            if evidence:
                meta["evidence"] = list(evidence)
        newline = "\r\n" if original.startswith(b"---\r\n") else "\n"
        head = yaml.dump(meta, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=10**6)
        updated = ("---\n" + head + "---\n").replace("\n", newline).encode("utf-8")
        updated += original[match.end():]
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".thought-status-", delete=False) as out:
                temporary = Path(out.name)
                os.fchmod(out.fileno(), stat.S_IMODE(path.stat().st_mode))
                out.write(updated)
                out.flush()
                os.fsync(out.fileno())
            # Refuse to overwrite an edit from a writer that ignores our lock.
            if path.read_bytes() != original:
                raise ValueError("thought changed during update; retry")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0], epilog=__doc__)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("thought", help="title or vault-relative Thoughts/path.md")
    parser.add_argument("--reopen", action="store_true", help="set todo and clear closure metadata")
    parser.add_argument("--reason")
    parser.add_argument("--resolution")
    parser.add_argument("--evidence", action="append", default=[], help="repeat for multiple evidence links or text")
    parser.add_argument("--lock", type=Path, help="shared writer lock (default: VAULT/.note-extract.lock)")
    args = parser.parse_args()
    try:
        path = change_status(args.vault, args.thought, reopen=args.reopen, reason=args.reason,
                             resolution=args.resolution, evidence=args.evidence, lock=args.lock)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        parser.exit(1, f"thought-status: {exc}\n")
    print(f"{path}: {'todo' if args.reopen else 'dealt-with'}")


if __name__ == "__main__":
    main()
