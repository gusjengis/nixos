#!/usr/bin/env python3
"""Protect new clone/init destinations before invoking the installed Git.

Only clone/init are guarded. Other commands (notably worktree add), aliases,
external Git invocations, and direct filesystem writes bypass this guard.
Unknown syntax in sessions requires an explicit, supported invocation instead.
No hooks or working_directory changes are installed here.
"""

import os
from pathlib import Path
import re
import signal
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

import repositories


class Unsupported(Exception):
    pass


CLONE_VALUES = {
    "--branch", "--depth", "--origin", "--config", "--template", "--reference",
    "--reference-if-able", "--separate-git-dir", "--upload-pack", "--filter",
    "--shallow-since", "--shallow-exclude", "--jobs", "--server-option", "--revision",
}
CLONE_FLAGS = {
    "--no-checkout", "--bare", "--mirror", "--quiet", "--verbose", "--progress",
    "--local", "--no-local", "--shared", "--no-hardlinks", "--dissociate",
    "--single-branch", "--no-single-branch", "--shallow-submodules",
    "--no-shallow-submodules", "--remote-submodules", "--no-remote-submodules",
    "--sparse", "--reject-shallow", "--no-reject-shallow", "--also-filter-submodules",
    "--no-tags", "--tags", "--no-progress", "--ipv4", "--ipv6",
}
INIT_VALUES = {"--template", "--separate-git-dir", "--object-format", "--ref-format",
               "--initial-branch"}
INIT_FLAGS = {"--quiet", "--bare"}


def _config_safe(value):
    key = value.split("=", 1)[0].lower()
    return key not in {"core.worktree", "core.bare"} and not key.startswith(("include.", "includeif."))


def _globals(args):
    cwd = Path.cwd()
    safe = True
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-") or arg == "-":
            return cwd, index, safe
        if arg in {"--help", "--version", "-h", "-v"}:
            return cwd, len(args), safe
        if arg in {"-C", "-c", "--config-env", "--git-dir", "--work-tree", "--namespace",
                   "--super-prefix", "--attr-source"}:
            if index + 1 == len(args):
                return cwd, len(args), False
            key, value = arg, args[index + 1]
            index += 2
        elif arg.startswith(("-C", "-c")) and len(arg) > 2:
            key, value = arg[:2], arg[2:]
            index += 1
        elif arg.startswith(("--config-env=", "--git-dir=", "--work-tree=", "--namespace=",
                             "--super-prefix=", "--attr-source=")):
            key, value = arg.split("=", 1)
            index += 1
        else:
            safe &= arg in {"--no-pager", "--paginate", "-p", "-P", "--no-replace-objects",
                             "--no-optional-locks", "--no-lazy-fetch", "--literal-pathspecs",
                             "--glob-pathspecs", "--noglob-pathspecs", "--icase-pathspecs"}
            index += 1
            continue
        if key == "-C":
            if value:
                cwd = (cwd / value).resolve()
        elif key in {"-c", "--config-env"}:
            safe &= "=" in value and _config_safe(value)
            if key == "--config-env":
                safe &= value.split("=", 1)[-1] in os.environ
        else:
            safe = False
    return cwd, index, safe


def _options(command, args):
    values = CLONE_VALUES if command == "clone" else INIT_VALUES
    flags = CLONE_FLAGS if command == "clone" else INIT_FLAGS
    short_values = {"-b", "-o", "-c", "-u", "-j"} if command == "clone" else {"-b"}
    short_flags = "nqvls46" if command == "clone" else "q"
    operands = []
    safe = True
    bare = False
    help_requested = False
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--":
            operands.extend(args[index:])
            break
        if not arg.startswith("-") or arg == "-":
            operands.append(arg)
            continue
        key, equal, value = arg.partition("=")
        if arg in {"--help", "-h"}:
            help_requested = True
        elif key in values:
            if not equal:
                if index == len(args):
                    safe = False
                    continue
                value = args[index]
                index += 1
            safe &= bool(value) and key != "--separate-git-dir"
            if key == "--config":
                safe &= _config_safe(value)
        elif arg[:2] in short_values:
            key, value = arg[:2], arg[2:]
            if not value:
                if index == len(args):
                    safe = False
                    continue
                value = args[index]
                index += 1
            safe &= bool(value)
            if key == "-c":
                safe &= _config_safe(value)
        elif key in ({"--recurse-submodules", "--recursive"} if command == "clone" else {"--shared"}):
            pass  # Optional arguments must use '=' in Git as well.
        elif arg in flags:
            bare |= arg in {"--bare", "--mirror"}
        elif arg.startswith("-") and not arg.startswith("--") and all(c in short_flags for c in arg[1:]):
            pass
        else:
            safe = False
    return operands, safe, bare, help_requested


def _clone_name(remote, bare):
    # Git's name guessing has transport-specific edge cases. Do not predict
    # those: the caller can always supply an explicit destination instead.
    if any(c.isspace() or ord(c) < 32 for c in remote) or "\\" in remote:
        raise Unsupported("Cannot infer clone directory; supply explicit destination")
    if "://" in remote:
        parsed = urlsplit(remote)
        if parsed.scheme not in {"https", "http", "ssh", "git", "file"} or parsed.query or parsed.fragment:
            raise Unsupported("Cannot infer clone directory; supply explicit destination")
        path = parsed.path
    elif re.match(r"(?:[^/@:]+@)?[^/:]+:.+", remote):
        path = remote.split(":", 1)[1]
    elif ":" in remote or "?" in remote or "#" in remote:
        raise Unsupported("Cannot infer clone directory; supply explicit destination")
    else:
        path = remote
    path = path.rstrip("/")
    if path.endswith("/.git"):
        path = path[:-5].rstrip("/")
    name = path.rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    if (not re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9._-]*", name)
            or name.endswith(".bundle")):
        raise Unsupported("Cannot infer clone directory; supply explicit destination")
    return name + (".git" if bare else "")


def _public_url(remote):
    # Local paths and scp syntax may themselves contain secrets. Omit them.
    try:
        parsed = urlsplit(remote)
        if parsed.scheme not in {"https", "http", "ssh", "git"} or not parsed.hostname:
            return None
        host = parsed.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    except ValueError:
        return None


def _protect(args, root):
    cwd, index, global_safe = _globals(args)
    if index == len(args) or args[index] not in {"clone", "init"}:
        return
    command, tail = args[index], args[index + 1:]
    operands, safe, bare, help_requested = _options(command, tail)
    if help_requested and safe:
        return
    safe &= global_safe
    destination = None
    try:
        if command == "clone" and len(operands) in {1, 2}:
            destination = (cwd / (operands[1] if len(operands) == 2 else _clone_name(operands[0], bare))).resolve()
        elif command == "init" and len(operands) <= 1:
            destination = (cwd / operands[0] if operands else cwd).resolve()
        else:
            safe = False
    except (Unsupported, ValueError):
        safe = False
    # With unknown syntax, any argument could be a destination, even an option
    # value. Never let an unknown option hide an absolute path into sessions.
    overrides = [(cwd / os.environ[name]).resolve() for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
    ) if os.environ.get(name)]
    if any(path.is_relative_to(root) for path in overrides):
        safe = False
    candidates = [destination] if safe and destination is not None else [cwd, *overrides]
    if not safe:
        for arg in args:
            if arg and not arg.startswith("-"):
                candidates.append((cwd / arg).resolve())
            elif "=" in arg:
                candidates.append((cwd / arg.split("=", 1)[1]).resolve())
    if not any(path.is_relative_to(root) for path in candidates):
        return
    if not safe or destination is None:
        raise Unsupported("Unsupported clone/init syntax in sessions; use supported options and explicit destination")
    if not destination.is_relative_to(root):
        return
    context = repositories.owning_context(root, destination)
    if context is None:
        raise Unsupported("Destination in sessions has no owning context")
    if any(name in os.environ for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS",
    )):
        raise Unsupported("Git location/config environment overrides unsupported in sessions")
    existing = any(item["path"].resolve() == destination for item in repositories.registered(root))
    if destination.exists():
        if not destination.is_dir():
            raise Unsupported("Repository destination is not a directory")
        git_directory = destination / ".git"
        if command == "init" and (git_directory.is_symlink() or git_directory.is_file()
                                  or (git_directory / "commondir").exists()):
            raise Unsupported("Separate Git directories unsupported in sessions")
        nonempty = any(destination.iterdir())
        if nonempty and not (command == "init" and existing and git_directory.is_dir()):
            raise Unsupported("Nonempty destination requires explicit adoption before clone/init")
    repositories.register(root, context, destination,
                          _public_url(operands[0]) if command == "clone" else None)
    repositories.sync(root, require_live=True)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    realgit = os.environ.get("CONTEXT_REAL_GIT", "")
    if not Path(realgit).is_absolute():
        print("context-git: CONTEXT_REAL_GIT must name absolute installed Git binary", file=sys.stderr)
        return 1
    try:
        if Path(realgit).resolve() == Path(__file__).resolve():
            raise Unsupported("CONTEXT_REAL_GIT must not point to wrapper")
        root = Path(os.environ.get("CONTEXT_ROOT", Path.home() / "sessions")).resolve()
        _protect(args, root)
    except (Unsupported, repositories.RepositoryError) as error:
        print(f"context-git: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError):
        print("context-git: cannot validate destination; Git not run", file=sys.stderr)
        return 1
    try:
        return subprocess.run([realgit, *args]).returncode
    except OSError:
        print("context-git: cannot run installed Git", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return -signal.SIGINT


if __name__ == "__main__":
    code = main()
    if code < 0:
        signal.signal(-code, signal.SIG_DFL)
        os.kill(os.getpid(), -code)
    sys.exit(code)
