#!/usr/bin/env python3
"""Snapshot V1 inputs for V2 upgrade checks without writable live state.

The sandbox retains the installed policy/configuration and uses a read-only host
mount, a private home, runtime, temporary directory, PID namespace, and network.
Snapshots use SQLite's online backup API, never copies of live WAL files.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys


MODULE = Path(__file__).resolve().parent
HOME = Path.home()


def digest(file):
    return hashlib.file_digest(file.open("rb"), "sha256").hexdigest()


def snapshot(root):
    if root.exists():
        raise SystemExit(f"Snapshot already exists; choose a new directory: {root}")
    root.mkdir(mode=0o700, parents=True)
    os.chmod(root, 0o700)
    home = root / "home"
    home.mkdir(mode=0o700)
    shutil.copytree(MODULE, root / "module", symlinks=True)
    contexts = MODULE.parent.parent / "desktop/contexts"
    shutil.copytree(contexts, root / "contexts", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(MODULE.parent.parent / "desktop/quickshell", root / "quickshell", symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__"))
    config = HOME / ".config/opencode"
    # Preserve symlinks: the repository module is mounted at its original path
    # inside the sandbox, so imports relative to symlink targets remain valid.
    shutil.copytree(config, home / ".config/opencode", symlinks=True,
                    ignore=shutil.ignore_patterns("*.lock"))
    state = home / ".local/state/opencode"
    state.parent.mkdir(parents=True)
    source_state = HOME / ".local/state/opencode"
    shutil.copytree(source_state, state, symlinks=False)
    data = home / ".local/share/opencode"
    data.mkdir(parents=True)
    source_data = HOME / ".local/share/opencode"
    auth = source_data / "auth.json"
    if auth.is_file():
        shutil.copy2(auth, data / auth.name)
        os.chmod(data / auth.name, 0o600)
    manifest = {"module": str(MODULE), "home": str(HOME), "databases": {}, "inputs": {}}
    for file in (config / "opencode.json", config / "tui.json", config / "cli.json"):
        if file.is_file():
            manifest["inputs"][str(file)] = digest(file)
    # The normal v1 database is the supported migration source. Other channels
    # are separate installations, not additional files belonging to this DB.
    source = source_data / "opencode.db"
    if source.is_file():
        target = data / source.name
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as reader:
            with sqlite3.connect(target) as writer:
                reader.backup(writer, pages=4096, sleep=0.05)
                result = writer.execute("PRAGMA quick_check").fetchone()[0]
                if result != "ok":
                    raise RuntimeError(f"Snapshot quick_check failed: {result}")
                count = writer.execute("SELECT count(*) FROM session").fetchone()[0]
        manifest["databases"][source.name] = {"sessions": count, "quick_check": result}
    # Resolve file substitutions within the private home, without displaying keys.
    key = HOME / ".config/secrets/api_keys/nvidia"
    if key.is_file():
        target = home / ".config/secrets/api_keys/nvidia"
        target.parent.mkdir(parents=True)
        shutil.copy2(key, target)
        os.chmod(target, 0o600)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"snapshot": str(root), "databases": manifest["databases"]}))


def run(root, bwrap, command):
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["module"] != str(MODULE) or manifest["home"] != str(HOME):
        raise SystemExit("Snapshot belongs to a different module/home")
    if not command:
        raise SystemExit("Supply a command after --")
    # Clear inherited OpenCode/context variables: they can select the live
    # server, DB, project, or desktop. Only neutral terminal/path settings remain.
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "TERM", "COLORTERM", "LANG", "LC_ALL", "SSL_CERT_FILE", "NIX_SSL_CERT_FILE"}}
    env["PATH"] = os.pathsep.join(dict.fromkeys(
        str(Path(entry).resolve()) for entry in env.get("PATH", "").split(os.pathsep) if entry))
    env.update({"HOME": str(HOME), "USER": HOME.name,
                "XDG_CONFIG_HOME": str(HOME / ".config"),
                "XDG_DATA_HOME": str(HOME / ".local/share"),
                "XDG_STATE_HOME": str(HOME / ".local/state"),
                "XDG_CACHE_HOME": str(HOME / ".cache"),
                "XDG_RUNTIME_DIR": "/run/user/sandbox"})
    args = [str(bwrap), "--ro-bind", "/", "/", "--unshare-pid", "--unshare-ipc", "--unshare-net",
            "--die-with-parent", "--new-session", "--proc", "/proc", "--dev", "/dev",
            "--tmpfs", "/tmp", "--dir", "/tmp/opencode", "--tmpfs", "/run", "--dir", "/run/user/sandbox",
            "--bind", str(root), "/tmp/work", "--bind", str(root / "home"), str(HOME),
            "--bind", str(root / "module"), str(MODULE)]
    if (root / "contexts").is_dir():
        args += ["--bind", str(root / "contexts"), str(MODULE.parent.parent / "desktop/contexts")]
    if (root / "quickshell").is_dir():
        args += ["--bind", str(root / "quickshell"), str(MODULE.parent.parent / "desktop/quickshell")]
    args += ["--chdir", "/tmp/work", "--", *command]
    return subprocess.run(args, env=env).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "run"])
    parser.add_argument("root", type=Path)
    parser.add_argument("--bwrap", type=Path, default=shutil.which("bwrap"))
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == "snapshot":
        snapshot(root)
        return 0
    if not args.bwrap:
        parser.error("bubblewrap required; supply --bwrap before action")
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    return run(root, args.bwrap, command)


if __name__ == "__main__":
    sys.exit(main())
