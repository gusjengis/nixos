#!/usr/bin/env python3
"""Persistent notebooks; compositor sessions remain disposable runtime state."""

import argparse
from contextlib import contextmanager, nullcontext
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

import repositories

missing_directories = set()


class ContextError(Exception):
    pass


def root():
    return Path(os.environ.get("CONTEXT_ROOT", str(Path.home() / "sessions"))).absolute()


def state_root():
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "desktop-contexts"


def signature():
    value = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "offline")
    if not value or "/" in value or value in (".", ".."):
        raise ContextError("Invalid compositor signature")
    return value


def runtime_path(prefix):
    directory = os.environ.get("XDG_RUNTIME_DIR")
    if not directory:
        raise ContextError("XDG_RUNTIME_DIR is required")
    return Path(directory) / f"{prefix}-{signature()}.json"


def read_json(path, default=None):
    try:
        with path.open() as stream:
            return json.load(stream)
    except FileNotFoundError:
        if default is not None:
            return default
        raise ContextError(f"Missing JSON file: {path}") from None
    except (ValueError, OSError) as exc:
        raise ContextError(f"Cannot read {path}: {exc}") from exc


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".contextctl-", delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream, ensure_ascii=True, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def mutation_lock():
    state_root().mkdir(parents=True, exist_ok=True)
    with (state_root() / "contextctl.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


@contextmanager
def runtime_operation(runtime_id):
    state_root().mkdir(parents=True, exist_ok=True)
    key = uuid.uuid5(uuid.NAMESPACE_URL, runtime_id).hex
    with (state_root() / f"close-{key}.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ContextError("This session is already being restored or saved for closure") from None
        yield


def relative_name(value, leaf=False):
    parts = value.split("/")
    if (not value or value != value.strip() or (leaf and len(parts) != 1)
            or any(not part or part.startswith(".")
                   or any(ord(char) < 32 or ord(char) == 127 for char in part) for part in parts)):
        raise ContextError(f"Invalid context name: {value!r}")
    return Path(*parts)


def contained(base, path):
    if not path.resolve().is_relative_to(base.resolve()):
        raise ContextError(f"Path escapes context: {path}")
    return path


def working_path(directory, value):
    if (not isinstance(value, str) or not value or ".." in value.split("/")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise ContextError(f"Invalid working_directory: {value!r}")
    if Path(value).is_absolute():
        return Path(value)
    return contained(directory, directory / value)


def scan():
    contexts = []
    seen = set()
    checkouts = set()
    if not root().exists():
        return contexts
    for directory, children, _ in os.walk(root(), followlinks=False):
        directory = Path(directory)
        if ".context" in children:
            relative = directory.relative_to(root()).as_posix()
            relative_name(relative)
            metadata = contained(directory, directory / ".context/context.json")
            data = read_json(metadata)
            try:
                paths = repositories.repository_paths(directory, data)
                checkouts.update(path for checkout in paths for path in (checkout, checkout.resolve()))
            except repositories.RepositoryError as exc:
                raise ContextError(str(exc)) from exc
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ContextError(f"Invalid context metadata: {metadata}")
            try:
                identifier = str(uuid.UUID(data["id"]))
            except (KeyError, ValueError, TypeError, AttributeError):
                raise ContextError(f"Invalid context UUID: {metadata}") from None
            if identifier != data["id"] or data.get("name") != directory.name:
                raise ContextError(f"Context metadata/name conflict: {metadata}")
            if identifier in seen:
                raise ContextError(f"Duplicate context ID: {identifier}")
            seen.add(identifier)
            vault = contained(directory, directory / ".context/notes")
            if not vault.is_dir() or not (vault / ".obsidian").is_dir():
                raise ContextError(f"Incomplete note vault: {vault}")
            cwd = working_path(directory, data.get("working_directory"))
            configured_cwd = cwd
            available = cwd.is_dir()
            if not available:
                if cwd not in missing_directories:
                    print(f"contextctl: Missing working directory {cwd}; using {directory}; notebook remains available", file=sys.stderr)
                    missing_directories.add(cwd)
                cwd = directory
            else:
                missing_directories.discard(cwd)
            contexts.append({"id": identifier, "name": relative, "label": relative,
                             "path": str(directory.absolute()), "cwd": str(cwd.absolute()),
                             "working_directory": data["working_directory"],
                             "working_directory_path": str(configured_cwd.absolute()),
                             "working_directory_available": available})
        children[:] = sorted(child for child in children if not child.startswith(".")
                             and directory / child not in checkouts and not (directory / child).is_symlink())
    return sorted(contexts, key=lambda item: item["name"])


def local_state():
    value = read_json(state_root() / f"{signature()}.json", {"mappings": {}, "last_active": None})
    if (not isinstance(value, dict) or not isinstance(value.get("mappings"), dict)
            or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value["mappings"].items())
            or len(set(value["mappings"].values())) != len(value["mappings"])):
        raise ContextError("Invalid local runtime mappings")
    return value


def save_state(value):
    atomic_json(state_root() / f"{signature()}.json", value)


def snapshot():
    value = read_json(runtime_path("hyprland-sessions"), {"sessions": [], "active": None})
    if not isinstance(value, dict) or not isinstance(value.get("sessions"), list):
        raise ContextError("Invalid runtime snapshot")
    ids = set()
    for item in value["sessions"]:
        if (not isinstance(item, dict) or not isinstance(item.get("id"), str)
                or not isinstance(item.get("name"), str) or item["id"] in ids):
            raise ContextError("Invalid runtime session")
        ids.add(item["id"])
    return value


def catalog():
    contexts, local, live = scan(), local_state(), snapshot()
    sessions = {item["id"]: item for item in live["sessions"]}
    active = None
    for item in contexts:
        runtime_id = local["mappings"].get(item["id"])
        session = sessions.get(runtime_id)
        item.update(runtime_id=runtime_id if session else None,
                    window_count=session.get("window_count", 0) if session else 0,
                    closing=bool(session.get("closing", False)) if session else False)
        if session and runtime_id == live.get("active"):
            active = item["id"]
    import organization
    return {"contexts": contexts, "active_context": active,
            "nodes": organization.resolve(contexts), "can_undo": organization.can_undo()}


def publish(record_activation=False):
    value = catalog()
    path = runtime_path("desktop-contexts")
    if read_json(path, {}) != value:
        atomic_json(path, value)
    if record_activation:
        local = local_state()
        if local.get("last_active") != value["active_context"]:
            local["last_active"] = value["active_context"]
            save_state(local)
    return value


def find_context(identifier):
    for item in scan():
        if item["id"] == identifier:
            return item
    raise ContextError(f"Unknown context: {identifier}")


def set_working_directory(identifier, value):
    """Caller holds mutation_lock; update configuration without moving live panes."""
    item = find_context(identifier)
    directory = Path(item["path"])
    working_path(directory, value)
    metadata = contained(directory, directory / ".context/context.json")
    data = read_json(metadata)
    data["working_directory"] = value
    atomic_json(metadata, data)


def create(name, working_directory=".", locked=False):
    """Create without launching applications. Safe for migration callers."""
    with nullcontext() if locked else mutation_lock():
        scan()  # Never mutate a conflicted or incomplete synced tree.
        directory = contained(root(), root() / relative_name(name))
        if any(directory.resolve().is_relative_to(item["path"].resolve()) for item in repositories.registered(root())):
            raise ContextError("Contexts cannot be created inside a registered Git checkout")
        working_path(directory, working_directory)
        metadata = directory / ".context/context.json"
        if metadata.exists() or (directory / ".context").exists():
            raise ContextError(f"Context already exists or is incomplete: {name}")
        notes = contained(directory, directory / ".context/notes")
        notes.mkdir(parents=True, exist_ok=True)
        (notes / ".obsidian").mkdir(exist_ok=True)
        for filename, value in (("app.json", {}), ("appearance.json", {})):
            path = notes / ".obsidian" / filename
            if not path.exists():
                atomic_json(path, value)
        with (notes / "Home.md").open("x") as stream:
            stream.write(f"# {directory.name}\n\n## Now\n\n\n## Next\n\n- [ ] \n\n"
                         "## Working Notes\n\n\n## Return Point\n\n")
        data = {"version": 1, "id": str(uuid.uuid4()), "name": directory.name,
                "working_directory": working_directory, "repositories": []}
        atomic_json(metadata, data)
        return data


def lua_string(value):
    # Decimal byte escapes are Lua-compatible, unlike JSON's Unicode escapes.
    return '"' + "".join(f"\\{byte:03d}" for byte in value.encode("utf-8")) + '"'


def evaluate(statement):
    result = subprocess.run(["hyprctl", "eval", statement], capture_output=True, text=True, timeout=3)
    output = result.stdout.strip()
    if result.returncode or output != "ok" or result.stderr.strip():
        raise ContextError(f"hyprctl eval failed: {output} {result.stderr.strip()}")


def clients():
    result = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True, timeout=3)
    if result.returncode:
        raise ContextError("Cannot inspect existing note windows")
    value = json.loads(result.stdout)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ContextError("Invalid client snapshot")
    return value


def process_profile(pid):
    if type(pid) is not int or pid <= 0:
        return None
    try:
        arguments = (Path("/proc") / str(pid) / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return None  # The process may have exited, or procfs may deny access.
    profiles = [os.fsdecode(argument[len(b"--user-data-dir="):]) for argument in arguments
                if argument.startswith(b"--user-data-dir=")]
    # Electron rewrites argv into one process-title string after startup.
    if not profiles and len([argument for argument in arguments if argument]) == 1:
        title = os.fsdecode(arguments[0])
        match = re.search(r"(?:^| )--class=context-notes-([0-9a-f-]{36})(?: |$)", title)
        if match:
            profile = str(state_root() / "obsidian" / match[1])
            if f" --user-data-dir={profile} --class=context-notes-{match[1]}" in title:
                profiles = [profile]
    return profiles[0] if len(profiles) == 1 else None


def note_context(client, contexts):
    # Native Wayland may ignore --class; the main PID retains its profile argument.
    profile = process_profile(client.get("pid"))
    for item in contexts:
        if profile == str(state_root() / "obsidian" / item["id"]):
            return item
    return next((item for item in contexts
                 if client.get("class") == f"context-notes-{item['id']}"), None)


def route_note(client, item):
    runtime_id = item.get("runtime_id")
    if (not runtime_id or local_state()["mappings"].get(item["id"]) != runtime_id
            or not any(entry["id"] == runtime_id for entry in snapshot()["sessions"])):
        return
    workspace = f"special:session-{runtime_id}-notes"
    current = client.get("workspace") or {}
    if (current.get("address") or current.get("name")) == workspace:
        return
    address = client.get("address")
    if not isinstance(address, str) or not address:
        raise ContextError("Existing note window has no address")
    evaluate("local r=hl.dispatch(hl.dsp.window.move({window="
             + lua_string("address:" + address) + ",workspace="
             + lua_string(workspace) + ",follow=false})); assert(r.ok, r.error)")


def reconcile_notes(contexts):
    live = [item for item in contexts if item["runtime_id"]]
    if not live:
        return
    for client in clients():
        item = note_context(client, live)
        if item is not None:
            route_note(client, item)


def open_context(identifier, background=False):
    with mutation_lock():
        item, runtime_id, created = prepare_open(identifier)
        publish()
    import persistence
    # Lifecycle bookkeeping uses only the short publication lock. Application
    # startup must never run while holding the global catalog/launcher lock.
    persistence.set_lifecycle(item, "open")
    if created:
        if background:
            spawn([sys.executable, "-B", str(Path(__file__).absolute()), "restore-runtime", identifier, runtime_id])
        else:
            restore_context(identifier, runtime_id)


def restore_context(identifier, runtime_id):
    import persistence
    with runtime_operation(runtime_id):
        with mutation_lock():
            item = launch_context(runtime_id)
            if item is None or item["id"] != identifier:
                raise ContextError("Context/runtime mapping changed before restoration")
        persistence.restore(item, runtime_id)


def prepare_open(identifier):
    """Create/switch runtime and save mapping; caller holds mutation_lock."""
    item = find_context(identifier)
    local, live = local_state(), snapshot()
    runtime_id = local["mappings"].get(identifier)
    session = next((entry for entry in live["sessions"] if entry["id"] == runtime_id), None)
    if session:
        evaluate(f"require('sessions').switch({lua_string(runtime_id)})")
        return item, runtime_id, False
    if any(entry["name"] == item["name"] for entry in live["sessions"]):
        raise ContextError(f"Unmapped runtime session already named {item['name']!r}; refusing to claim it")
    evaluate(f"require('sessions').create({lua_string(item['name'])})")
    deadline = time.monotonic() + 2
    while True:
        matches = [entry for entry in snapshot()["sessions"] if entry["name"] == item["name"]]
        if len(matches) == 1:
            runtime_id = matches[0]["id"]
            break
        if len(matches) > 1 or time.monotonic() >= deadline:
            raise ContextError("Created runtime session not uniquely visible in snapshot")
        time.sleep(0.05)
    if runtime_id in {value for key, value in local["mappings"].items() if key != identifier}:
        raise ContextError("Created runtime ID is already mapped to another context")
    local["mappings"][identifier] = runtime_id
    save_state(local)
    if snapshot().get("active") != runtime_id:
        raise ContextError("Active runtime changed before opening notes; mapping saved")
    evaluate("require('sessions').show_special('notes')")
    return item, runtime_id, True


def rename_context(identifier, new_name):
    relative_name(new_name, leaf=True)
    item = find_context(identifier)
    directory = Path(item["path"])
    affected = [entry for entry in catalog()["contexts"]
                if Path(entry["path"]).is_relative_to(directory)]
    if any(read_json(Path(entry["path"]) / ".context/context.json").get("repositories")
           for entry in affected):
        raise ContextError("Repository contexts cannot be renamed yet; Git sync paths and compatibility links must change together")
    if any(entry["runtime_id"] for entry in affected):
        raise ContextError("Close context and descendant runtime sessions before renaming")
    if any(note_context(client, affected) is not None for client in clients()):
        raise ContextError("Close note vault windows before renaming")
    target = contained(root(), directory.with_name(new_name))
    if target.exists():
        raise ContextError(f"Destination already exists: {target}")
    data = read_json(directory / ".context/context.json")
    directory.rename(target)
    data["name"] = new_name
    try:
        atomic_json(target / ".context/context.json", data)
    except OSError:
        target.rename(directory)
        raise


def launch_context(runtime_id=None):
    if runtime_id is not None and not any(entry["id"] == runtime_id for entry in snapshot()["sessions"]):
        raise ContextError(f"Runtime session has closed: {runtime_id}")
    value = catalog()
    if runtime_id is None:
        identifier = value["active_context"]
        return next((item for item in value["contexts"] if item["id"] == identifier), None)
    return next((item for item in value["contexts"] if item["runtime_id"] == runtime_id), None)


def spawn(arguments):
    subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def notes(runtime_id=None):
    item = launch_context(runtime_id)
    if item is None:
        # Runtime-only sessions retain the original general-notebook shortcut.
        spawn(["obsidian"])
        return
    vault = contained(Path(item["path"]), Path(item["path"]) / ".context/notes")
    if not vault.is_dir():
        raise ContextError(f"Incomplete note vault: {vault}")
    workspace_file = vault / ".obsidian/workspace.json"
    if not workspace_file.exists():
        # Start from native workspace state; startup URI handling races vault loading.
        initial_note = "Home.md" if (vault / "Home.md").is_file() else None
        initial_state = ({"type": "markdown", "state": {"file": initial_note, "mode": "source", "source": False}}
                         if initial_note else {"type": "empty", "state": {}})
        atomic_json(workspace_file, {
            "main": {"id": "context-main", "type": "split", "direction": "vertical", "children": [
                {"id": "context-tabs", "type": "tabs", "children": [
                    {"id": "context-home", "type": "leaf", "state": initial_state}
                ]}
            ]}, "active": "context-home"
        })
    window_class = f"context-notes-{item['id']}"
    for client in clients():
        if note_context(client, [item]) is not None:
            route_note(client, item)
            return
    profile = state_root() / "obsidian" / item["id"]
    config_path = profile / "obsidian.json"
    config = read_json(config_path, {})
    if not isinstance(config, dict) or not isinstance(config.get("vaults", {}), dict):
        raise ContextError(f"Invalid Obsidian profile: {config_path}")
    vaults = config.setdefault("vaults", {})
    vault_id = item["id"].replace("-", "")[:16]
    registration = vaults.setdefault(vault_id, {})
    if not isinstance(registration, dict):
        raise ContextError(f"Invalid vault registration: {config_path}")
    registration.update(path=str(vault), ts=int(time.time() * 1000), open=True)
    atomic_json(config_path, config)
    vault_state = profile / f"{vault_id}.json"
    if not vault_state.exists():
        atomic_json(vault_state, {})
    spawn(["obsidian", f"--user-data-dir={profile}", f"--class={window_class}"])


def terminal(runtime_id=None):
    item = launch_context(runtime_id)
    cwd = item["cwd"] if item else str(Path.home())
    if item:
        name = f"context-{item['id']}"
    else:
        runtime_id = runtime_id or snapshot().get("active")
        if not runtime_id:
            raise ContextError("No active runtime for terminal")
        name = f"desktop-{signature()}-{runtime_id}"
        # tmux treats periods and colons as target separators.
        name = name.replace(".", "_").replace(":", "_")
    arguments = ["kitty", "--directory", cwd, "--hold"]
    if item:
        arguments += ["env", f"CONTEXT_DIRECTORY={item['path']}", f"CONTEXT_ID={item['id']}"]
    spawn([*arguments, "create-tmux-session", cwd, name, "--attach"])


def close_kitty_windows(runtime_id):
    """Close only this runtime's Kitty OS windows, without interactive prompts.

    A shared Kitty process can host OS windows in several desktop contexts. Only
    use the socket when Kitty reports exactly one OS window and the compositor
    agrees; ambiguous instances and older processes keep normal close handling.
    """
    runtime = next((s for s in snapshot()["sessions"] if s["id"] == runtime_id), {})
    addresses = set(runtime.get("windows", []))
    if not addresses:
        return []
    windows = clients()
    handled = []
    for window in windows:
        address, pid = window.get("address"), window.get("pid")
        if address not in addresses or type(pid) is not int or pid <= 0:
            continue
        cls = window.get("initialClass") or window.get("class", "")
        if not cls.lower().startswith(("kitty", "context-terminal-")):
            continue
        if sum(w.get("pid") == pid for w in windows) != 1:
            continue
        endpoint = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / f"kitty-context-{pid}"
        if not endpoint.is_socket():
            continue
        command = ["kitty", "@", "--to", f"unix:{endpoint}", "--use-password", "never"]
        try:
            result = subprocess.run([*command, "ls"], capture_output=True, text=True, timeout=3)
            if result.returncode:
                continue
            tree = json.loads(result.stdout)
            if not isinstance(tree, list) or len(tree) != 1:
                continue
            ids = [w["id"] for tab in tree[0]["tabs"] for w in tab["windows"]]
            if not ids or any(type(identifier) is not int or identifier <= 0 for identifier in ids):
                continue
            match = " or ".join(f"id:{identifier}" for identifier in ids)
            result = subprocess.run([*command, "close-window", "--match", match],
                                    capture_output=True, text=True, timeout=3)
            if result.returncode == 0:
                handled.append(address)
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            # No force-kill fallback. Normal compositor closure remains available.
            continue
    return handled


def close_context(runtime_id):
    import persistence
    # Serialize retries for this runtime, not every context command. Capturing
    # applications may take seconds and must not block the catalog or launchers.
    with runtime_operation(runtime_id):
        with mutation_lock():
            item = launch_context(runtime_id)
        # Barrier still completes before compositor receives any close request.
        persistence.checkpoint("close", item["id"] if item else None)
        with mutation_lock():
            # Runtime IDs are never reused. Do not close another session if the
            # original disappeared while its applications were being captured.
            launch_context(runtime_id)
            handled = close_kitty_windows(runtime_id)
            persistence.set_lifecycle(item, "closed")
            addresses = "{" + ",".join("[" + lua_string(address) + "]=true" for address in handled) + "}"
            evaluate("require('context-terminals').close_checkpointed(" + lua_string(runtime_id) + "," + addresses + ")")
            publish()


def watch():
    previous_stamp = object()
    next_scan = 0
    while True:
        try:
            try:
                stamp = runtime_path("hyprland-sessions").stat().st_mtime_ns
            except FileNotFoundError:
                stamp = None
            # Periodic full scans also catch remote sync without runtime changes.
            if stamp != previous_stamp or time.monotonic() >= next_scan:
                previous_stamp = stamp
                next_scan = time.monotonic() + 1
                with mutation_lock():
                    value = publish(record_activation=True)
                import context_chat_library
                context_chat_library.refresh_scopes(value["contexts"])
                reconcile_notes(value["contexts"])
        except (ContextError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            print(f"contextctl: {exc}", file=sys.stderr)
        time.sleep(0.2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    command = commands.add_parser("create")
    command.add_argument("name")
    command.add_argument("--open", action="store_true")
    command.add_argument("--background", action="store_true", help="Restore applications in a detached worker")
    command = commands.add_parser("open")
    command.add_argument("id")
    command.add_argument("--background", action="store_true", help="Restore applications in a detached worker")
    command = commands.add_parser("restore-runtime", help=argparse.SUPPRESS)
    command.add_argument("id")
    command.add_argument("runtime")
    command = commands.add_parser("rename")
    command.add_argument("id")
    command.add_argument("name")
    command = commands.add_parser("set-working-directory")
    command.add_argument("id")
    command.add_argument("path")
    command = commands.add_parser("close")
    command.add_argument("--runtime", required=True)
    for name in ("notes", "terminal", "files"):
        command = commands.add_parser(name)
        command.add_argument("--runtime")
    commands.add_parser("watch")
    command = commands.add_parser("organize")
    actions = command.add_subparsers(dest="action", required=True)
    action = actions.add_parser("create")
    action.add_argument("name")
    action.add_argument("--parent")
    action = actions.add_parser("rename")
    action.add_argument("id")
    action.add_argument("name")
    action = actions.add_parser("move")
    action.add_argument("ids", nargs="+")
    action.add_argument("--parent")
    action = actions.add_parser("promote")
    action.add_argument("id")
    action = actions.add_parser("delete")
    action.add_argument("ids", nargs="+")
    action.add_argument("--confirm", action="store_true", required=True)
    actions.add_parser("undo")
    args = parser.parse_args(argv)
    try:
        if args.command == "watch":
            watch()
            return 0
        if args.command == "close":
            close_context(args.runtime)
            print("ok")
            return 0
        if args.command == "open":
            open_context(args.id, background=args.background)
            print("ok")
            return 0
        if args.command == "restore-runtime":
            restore_context(args.id, args.runtime)
            print("ok")
            return 0
        if args.command == "organize":
            import organization
            with mutation_lock():
                if args.action == "create":
                    identifier = organization.create(args.name, args.parent)
                elif args.action == "promote":
                    identifier = organization.promote(args.id)
                elif args.action == "rename":
                    organization.change([args.id], new_label=args.name)
                elif args.action == "move":
                    organization.change(args.ids, parent=args.parent)
                elif args.action == "delete":
                    organization.trash_contexts(args.ids)
                else:
                    organization.undo()
                publish()
            print(json.dumps({"id": identifier}) if args.action in ("create", "promote") else "ok")
            return 0
        if args.command == "create":
            data = create(args.name)
            if args.open:
                open_context(data["id"], background=args.background)
            else:
                with mutation_lock():
                    publish()
        else:
            with mutation_lock():
                if args.command == "list":
                    print(json.dumps(publish()))
                    return 0
                if args.command == "rename":
                    rename_context(args.id, args.name)
                elif args.command == "set-working-directory":
                    set_working_directory(args.id, args.path)
                elif args.command == "notes":
                    notes(args.runtime)
                elif args.command == "terminal":
                    terminal(args.runtime)
                elif args.command == "files":
                    item = launch_context(args.runtime)
                    spawn(["thunar", item["cwd"] if item else str(Path.home())])
                publish()
        print("ok")
        return 0
    except (ContextError, repositories.RepositoryError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"contextctl: {exc}", file=sys.stderr)
        if args.command == "restore-runtime":
            import persistence
            persistence.notify([f"Context restoration: {exc}"])
        return 1


if __name__ == "__main__":
    # Persistence imports this module for lifecycle primitives. Keep one class
    # identity when entered through the executable as well as through imports.
    sys.modules["contextctl"] = sys.modules[__name__]
    sys.exit(main())
