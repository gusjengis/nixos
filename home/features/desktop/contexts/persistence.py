"""Context terminal checkpoints: one current root, incremental immutable chunks."""

# Adapter boundaries must report any item failure and continue independent items.
# ruff: noqa: BLE001

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import copy
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import socket
import struct
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import chat_portability as chats
import checkpoint_store as store
import context_chat_library as chat_library
import contextctl as ctl
import window_close


class CheckpointError(ctl.ContextError):
    pass


class EditorInputBlocked(CheckpointError):
    pass


def run(args, timeout=15, **kwargs):
    # These are captured, noninteractive commands. In particular Neovim routes
    # remote-expr output to stderr (with terminal output on stdout) if it inherits
    # a TTY stdin while stdout is piped. Honor intentional input/stdin overrides.
    if "input" not in kwargs:
        kwargs.setdefault("stdin", subprocess.DEVNULL)
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True,
                            timeout=timeout, check=False, **kwargs)
    if result.returncode:
        raise CheckpointError(f"{args[0]}: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def local_root():
    return ctl.state_root() / "terminal"


def set_lifecycle(context, status):
    path = local_root() / "lifecycle.json"
    key = context["id"] if context else "local"
    if ctl.read_json(path, {}).get(key) == status:
        return
    with context_lock(context), file_lock("lifecycle"):
        value = ctl.read_json(path, {})
        value[key] = status
        write_json(path, value)


def write_json(path, value):
    if isinstance(path, store.MemoryPath):
        path.write_bytes(store.canonical(value))
    elif not path.exists() or ctl.read_json(path) != value:
        ctl.atomic_json(path, value)


def device():
    return re.sub(r"[^a-zA-Z0-9_-]", "_", socket.gethostname())


def report(message):
    directory = local_root()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "events.log").open("a") as stream:
        stream.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}\n")
    print(f"context-checkpoint: {message}", file=sys.stderr)


def notify(errors):
    # Workspace persistence is background convenience, not a call to action.
    # Keep diagnostics available without desktop popups (including restore).
    if errors:
        report("; ".join(sorted(set(errors))))


def discarded_editor(pane, discard=None):
    """Remember failed editor restores until a healthy capture replaces them."""
    path = local_root() / "discarded-editors.json"
    with file_lock("discarded-editors"):
        values = ctl.read_json(path, [])
        if discard is True and pane["id"] not in values:
            values.append(pane["id"])
        elif discard is False:
            values = [value for value in values if value != pane["id"]]
        if discard is not None:
            write_json(path, values)
        return pane["id"] in values


@contextmanager
def file_lock(name):
    local_root().mkdir(parents=True, exist_ok=True, mode=0o700)
    with (local_root() / (name + ".lock")).open("a") as stream:
        deadline = time.monotonic() + 60
        while True:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CheckpointError("Checkpoint busy for 60 seconds")
                time.sleep(.1)
        yield


def lock():
    return file_lock("checkpoint")


def context_lock(context):
    key = uuid.UUID(context["id"]).hex if context else "local"
    return file_lock("context-" + key)


def encode_path(path, context):
    path = Path(path).absolute()
    for kind, base in (("context", Path(context["path"]) if context else None), ("home", Path.home())):
        if base is not None and path.is_relative_to(base):
            return {"kind": kind, "path": str(path.relative_to(base))}
    return {"kind": "external", "path": str(path)}


def decode_path(value, context):
    kind, path = value["kind"], Path(value["path"])
    if kind == "external" and path.is_absolute():
        # Explicit machine-local mapping, never guess a replacement root.
        mappings = ctl.read_json(local_root() / "external-roots.json", {})
        for source in sorted(mappings, key=len, reverse=True):
            old, new = Path(source), Path(mappings[source])
            if not old.is_absolute() or not new.is_absolute():
                raise CheckpointError("External root mappings must use absolute paths")
            if path.is_relative_to(old):
                return new / path.relative_to(old)
        return path
    bases = {"home": Path.home(), "context": Path(context["path"]) if context else None}
    if kind not in bases or bases[kind] is None or path.is_absolute() or ".." in path.parts:
        raise CheckpointError(f"Invalid portable path: {value}")
    result = bases[kind] / path
    if kind == "context" and not result.resolve().is_relative_to(bases[kind].resolve()):
        raise CheckpointError(f"Portable path escapes {kind} root through symlink: {value}")
    return result


def state_dir(context):
    if context:
        base = Path(context["path"])
        return ctl.contained(base, base / ".context/state")
    return local_root() / "unowned"


def safe(base, relative):
    if isinstance(base, store.MemoryPath):
        return base / store.relative(relative)
    path = (base / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(base.resolve()):
        raise CheckpointError(f"Artifact escapes generation: {relative}")
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checkpoint_store(context):
    return store.Store(state_dir(context) / "terminal",
                       local_root() / "stores" / (context["id"] if context else "local"))


def latest(context):
    storage = checkpoint_store(context)
    try:
        current = storage.load()
        if current:
            if current["context_id"] != (context["id"] if context else None):
                raise CheckpointError("Checkpoint identity/schema mismatch")
            return storage.view(current), current
        if (storage.local / "witness.json").exists():
            raise CheckpointError("Latest checkpoint manifest missing/corrupt; no older fallback")
        return latest_v1(context)
    except ValueError as exc:
        raise CheckpointError(str(exc)) from exc


def latest_v1(context):
    directory = state_dir(context) / "terminal"
    heads = [ctl.read_json(path) for path in (directory / "heads").glob("*.json")]
    if not heads:
        return None
    head = max(heads, key=lambda h: (h["created_ns"], h["generation"]))
    base = safe(directory, head["generation"])
    manifest_path = base / "manifest.json"
    if not manifest_path.is_file() or digest(manifest_path) != head["sha256"]:
        raise CheckpointError("Latest checkpoint manifest missing/corrupt; wait for sync (no older fallback)")
    manifest = ctl.read_json(manifest_path)
    if manifest["version"] != 1 or manifest["context_id"] != (context["id"] if context else None):
        raise CheckpointError("Checkpoint identity/schema mismatch")
    return base, manifest


def validate(base, manifest, prefix=""):
    for relative, info in manifest["artifacts"].items():
        if prefix and not relative.startswith(prefix):
            continue
        path = safe(base, relative)
        try:
            valid = path.is_file() and len(path.read_bytes()) == info["size"] and digest(path) == info["sha256"]
        except ValueError as exc:
            raise CheckpointError(str(exc)) from exc
        if not valid:
            raise CheckpointError(f"Latest checkpoint artifact missing/corrupt: {relative}; wait for sync")


def validate_pane(base, manifest, pane):
    if pane.get("editor"):
        try:
            validate(base, manifest, f"nvim/{pane['id']}/")
        except Exception as exc:
            report(f"Editor {pane['id']}: {exc}; reopening fresh")
            discarded_editor(pane, True)
            pane.pop("editor", None)
            pane["command"] = "nvim"
    validate(base, manifest, f"opencode/{pane['id']}/")


class Tmux:
    def __init__(self, socket_path):
        self.socket = str(socket_path)

    def call(self, *args):
        return run([os.environ.get("PERSISTENCE_TMUX", "tmux"), "-S", self.socket, *args])

    def set_working_directory(self, target, directory):
        # attach-session -c is tmux's native session-cwd setter. A transient
        # control client needs no terminal and leaves existing clients/panes
        # alone. Do not inherit a nested-client marker or update session env.
        environment = dict(os.environ)
        environment.pop("TMUX", None)
        run([os.environ.get("PERSISTENCE_TMUX", "tmux"), "-S", self.socket,
             "-C", "attach-session", "-E", "-t", target,
             "-c", str(directory).replace("#", "##"), ";", "detach-client"], env=environment)

    def reachable(self):
        # A socket inode can survive a crashed server. Let new-session perform
        # tmux's native stale-socket recovery instead of treating it as live.
        try:
            with socket.socket(socket.AF_UNIX) as connection:
                connection.settimeout(1)
                connection.connect(self.socket)
                _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                if uid != os.getuid():
                    raise CheckpointError("Tmux socket belongs to another user")
                return True
        except (FileNotFoundError, ConnectionRefusedError):
            return False

    def rows(self, command, fields, *args):
        output = self.call(command, *args, "-F", " ".join("x#{q:" + field + "}" for field in fields))
        result = []
        for line in output.splitlines():
            values = shlex.split(line)
            if len(values) != len(fields):
                raise CheckpointError("Unsupported newline/control character in tmux metadata")
            result.append(dict(zip(fields, (value[1:] for value in values))))
        return result

    def identity(self, target, scope):
        option = "@persistence-window-id" if "-w" in scope else "@persistence-id" if "-p" in scope else "@persistence-session-id"
        value = self.call("show-options", *scope, "-v", "-t", target, option) if self.has_option(target, scope, option) else ""
        if not value:
            value = str(uuid.uuid4())
            self.call("set-option", *scope, "-t", target, option, value)
        uuid.UUID(value)
        return value

    def has_option(self, target, scope, option):
        return option + " " in self.call("show-options", *scope, "-t", target)


def sockets(extra=None):
    registry = ctl.read_json(local_root() / "sockets.json", [])
    candidates = [*registry, *(str(p) for p in Path(f"/tmp/tmux-{os.getuid()}").glob("*"))]
    if os.environ.get("TMUX"):
        candidates.append(os.environ["TMUX"].rsplit(",", 2)[0])
    if extra:
        candidates.append(str(extra))
    result = []
    for path in dict.fromkeys(candidates):
        try:
            if Path(path).is_socket():
                tm = Tmux(path)
                if tm.reachable():
                    result.append(tm)
        except OSError:
            pass
    write_json(local_root() / "sockets.json", [tm.socket for tm in result])
    return result


def owner(session, panes, contexts, resolve_paths=True):
    explicit = session.get("@persistence-context")
    if not explicit and session["session_name"].startswith("context-"):
        explicit = session["session_name"][8:]
    if explicit:
        found = next((c for c in contexts if c["id"] == explicit), None)
        if found is None:
            raise CheckpointError(f"Session claims unknown context {explicit}")
        return found
    owners = set()
    for pane in panes:
        path = Path(pane["pane_current_path"])
        path = path.resolve() if resolve_paths else path.absolute()
        matching = [c for c in contexts if path.is_relative_to(
            Path(c["path"]).resolve() if resolve_paths else Path(c["path"]).absolute())]
        owners.add(max(matching, key=lambda c: len(c["path"]))["id"] if matching else None)
    if len(owners) == 1 and None not in owners:
        return next(c for c in contexts if c["id"] in owners)
    return None


def descendant(pid, ancestor):
    seen = set()
    while pid > 1 and pid not in seen:
        if pid == ancestor:
            return True
        seen.add(pid)
        try:
            pid = int(Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[1])
        except (OSError, ValueError):
            break
    return False


def runtime_targets(tm, runtime_id):
    """Resolve runtime-only terminal attachments before inspecting any panes."""
    live = next((item for item in ctl.snapshot()["sessions"] if item["id"] == runtime_id), {})
    addresses = set(live.get("windows", []))
    windows = [item for item in ctl.clients() if item.get("address") in addresses]
    rows = tm.rows("list-clients", ["session_id", "client_pid"])
    targets = {row["session_id"] for row in rows if any(descendant(int(row["client_pid"]), window["pid"]) for window in windows)}
    name = f"desktop-{ctl.signature()}-{runtime_id}".replace(".", "_").replace(":", "_")
    targets.update(row["session_id"] for row in tm.rows("list-sessions", ["session_id"], "-f", "#{==:#{session_name}," + name + "}"))
    return sorted(targets)


def inventory(context, sessions):
    """Map terminal clients by process ancestry, not the currently active desktop."""
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return {"windows": [], "desktop": None, "warnings": []}
    raw = ctl.clients()
    monitors = json.loads(run(["hyprctl", "-j", "monitors"]))
    active = json.loads(run(["hyprctl", "-j", "activewindow"]))
    attachments = []
    for tm, session in sessions:
        for client in tm.rows("list-clients", ["client_pid", "session_id", "client_tty"], "-t", session["observed_id"]):
            attachments.append((client, session))

    runtime_id = ctl.local_state()["mappings"].get(context["id"]) if context else None
    remembered = next((s for s in ctl.snapshot()["sessions"] if s["id"] == runtime_id), {}) if runtime_id else {}
    result, warnings, focus_ranks = [], [], {}
    observed = ctl.read_json(local_root() / f"windows-{ctl.signature()}.json", {})
    present = {}
    for index, window in enumerate(raw):
        if not (window.get("class", "").lower().startswith(("kitty", "context-terminal-"))):
            continue
        matches = [s for client, s in attachments if descendant(int(client["client_pid"]), window["pid"])]
        workspace = window.get("workspace", {}).get("name", "")
        belongs = runtime_id and workspace.startswith((f"session-{runtime_id}-", f"special:session-{runtime_id}-"))
        if not matches and not belongs:
            continue
        key = f"{window['address']}:{window['pid']}"
        cls = window.get("class", "")
        logical = cls.removeprefix("context-terminal-") if cls.startswith("context-terminal-") else observed.get(key, str(uuid.uuid4()))
        present[key] = logical
        if isinstance(window.get("focusHistoryID"), int):
            focus_ranks[logical] = window["focusHistoryID"]
        if not matches:
            warnings.append(f"Terminal {logical} has no tmux attachment; live process cannot be restored")
        if len({s['id'] for s in matches}) > 1:
            raise CheckpointError("Terminal has ambiguous tmux client ownership")
        output = next((m for m in monitors if m["id"] == window.get("monitor")), monitors[0] if monitors else {})
        role, slot = None, None
        if runtime_id:
            prefix = f"special:session-{runtime_id}-"
            if workspace.startswith(prefix):
                role = workspace[len(prefix):]
            else:
                match = re.fullmatch(rf"session-{re.escape(runtime_id)}-[0-9a-f]+-(\d+)", workspace)
                if match:
                    slot = int(match[1])
        if slot is None and workspace.isdigit():
            slot = int(workspace)
        width = output.get("width", 1920) / output.get("scale", 1)
        height = output.get("height", 1080) / output.get("scale", 1)
        if output.get("transform", 0) % 2:
            width, height = height, width
        result.append({"id": logical, "session": matches[0]["id"] if matches else None,
                       "workspace": {"role": role, "slot": slot or 1}, "monitor": output.get("name"),
                       "floating": window.get("floating", False), "order": index,
                       "geometry": [(window.get("at", [0, 0])[0] - output.get("x", 0)) / width,
                                    (window.get("at", [0, 0])[1] - output.get("y", 0)) / height,
                                    window.get("size", [800, 600])[0] / width,
                                    window.get("size", [800, 600])[1] / height],
                       "fullscreen": window.get("fullscreen", 0),
                       "fullscreen_client": window.get("fullscreenClient", 0),
                       "focused": window["address"] == active.get("address")})
    observed.update(present)
    write_json(local_root() / f"windows-{ctl.signature()}.json", observed)
    if result and not any(w["focused"] for w in result):
        # Global focus belongs to another context. MRU rank still identifies this
        # context's last focused terminal, including nonvisible workspaces.
        min(result, key=lambda w: (focus_ranks.get(w["id"], float("inf")), w["order"]))["focused"] = True
    view = []
    for monitor in monitors:
        name = monitor.get("activeWorkspace", {}).get("name", "")
        special = monitor.get("specialWorkspace", {}).get("name", "")
        slot = re.search(r"-(\d+)$", name)
        prefix = f"special:session-{runtime_id}-"
        visible = runtime_id and name.startswith(f"session-{runtime_id}-")
        saved_slot = remembered.get("slots", {}).get(monitor["name"], 1)
        saved_role = remembered.get("visible_specials", {}).get(monitor["name"])
        view.append({"monitor": monitor["name"],
                     "slot": int(slot[1]) if slot and (visible or not remembered) else int(name) if name.isdigit() else saved_slot,
                     "role": special[len(prefix):] if runtime_id and special.startswith(prefix) else saved_role})
    return {"windows": result, "desktop": view, "warnings": warnings}


def capture_tmux(tm, contexts, session_targets=None):
    try:
        server_id = tm.call("show-options", "-s", "-v", "@persistence-server-id")
    except CheckpointError:
        server_id = str(uuid.uuid4())
        tm.call("set-option", "-s", "@persistence-server-id", server_id)
    uuid.UUID(server_id)
    session_fields = ["session_id", "session_name", "session_group", "@persistence-context", "@persistence-session-id"]
    pane_fields = ["session_id", "window_id", "pane_id", "pane_index", "pane_pid",
                      "pane_current_path", "pane_current_command", "pane_active", "pane_title",
                      "@persistence-editor", "@persistence-editor-socket", "@persistence-chat-socket",
                      "@persistence-recovery-pending", "@persistence-id"]
    window_fields = ["session_id", "window_id", "window_index", "window_name",
                      "window_layout", "window_active", "window_zoomed_flag", "automatic-rename", "@persistence-window-id", "@persistence-close-staged"]
    if session_targets is None:
        sessions = tm.rows("list-sessions", session_fields)
        all_panes = tm.rows("list-panes", pane_fields, "-a")
        windows = tm.rows("list-windows", window_fields, "-a")
    else:
        sessions, all_panes, windows = [], [], []
        for target in session_targets:
            sessions.extend(tm.rows("list-sessions", session_fields, "-f", "#{==:#{session_id}," + target + "}"))
            all_panes.extend(tm.rows("list-panes", pane_fields, "-s", "-t", target))
            windows.extend(tm.rows("list-windows", window_fields, "-t", target))
    # Read IDs in the inventory formats, not with two extra tmux processes per
    # object. Queue missing IDs and ownership metadata in bounded command batches.
    # Physical windows/panes can occur in several sessions or linked indices.
    identities, updates = {}, []

    def identity(row, target_key, option, scope=()):
        target = row[target_key]
        key = (option, target)
        if key not in identities:
            value = row[option]
            if not value:
                value = str(uuid.uuid4())
                updates.append(["set-option", *scope, "-t", target, option, value])
            uuid.UUID(value)
            identities[key] = value
        return identities[key]

    result = []
    for session in sessions:
        if session["session_name"].startswith(window_close.STAGING):
            continue
        own_panes = list({p["pane_id"]: p for p in all_panes
                          if p["session_id"] == session["session_id"]}.values())
        explicit = session.get("@persistence-context") or (
            session["session_name"][8:] if session["session_name"].startswith("context-") else None)
        orphaned = explicit if explicit and not any(c["id"] == explicit for c in contexts) else None
        # A removed context must not block capture of every other session. Keep
        # its live panes in machine-local recovery, retaining claimed identity;
        # never infer ownership from a different checkout or recreate its vault.
        context = None if orphaned else owner(session, own_panes, contexts, resolve_paths=False)
        if context:
            updates.extend([
                ["set-option", "-t", session["session_id"], "@persistence-context", context["id"]],
                ["set-environment", "-t", session["session_id"], "CONTEXT_DIRECTORY", context["path"]],
                ["set-environment", "-t", session["session_id"], "CONTEXT_ID", context["id"]],
            ])
        value = {"id": identity(session, "session_id", "@persistence-session-id"), "observed_id": session["session_id"],
                 "name": session["session_name"], "group": session["session_group"], "windows": [],
                  "server": {"id": server_id, "default": Path(tm.socket).name == "default"}}
        if orphaned:
            value["orphaned_context_id"] = orphaned
        for window in (w for w in windows if w["session_id"] == session["session_id"]):
            if window.get("@persistence-close-staged"):
                continue
            saved = {"id": identity(window, "window_id", "@persistence-window-id", ("-w",)), "index": int(window["window_index"]),
                     "name": window["window_name"], "layout": window["window_layout"],
                      "active": window["window_active"] == "1", "zoom": window["window_zoomed_flag"] == "1",
                      "automatic_rename": window["automatic-rename"] == "1", "panes": []}
            for pane in (p for p in own_panes if p["window_id"] == window["window_id"]):
                saved["panes"].append({"id": identity(pane, "pane_id", "@persistence-id", ("-p",)),
                    "index": int(pane["pane_index"]), "observed_id": pane["pane_id"],
                    "cwd": encode_path(pane["pane_current_path"], context),
                    "active": pane["pane_active"] == "1", "title": pane["pane_title"],
                    "command": pane["pane_current_command"], "local": pane})
            value["windows"].append(saved)
        result.append((context, tm, value))
    for offset in range(0, len(updates), 64):
        arguments = []
        for command in updates[offset:offset + 64]:
            if arguments:
                arguments.append(";")
            arguments.extend(command)
        tm.call(*arguments)
    return result


def context_servers(context, socket_path=None):
    """Known backing servers only; never ping another context's custom server."""
    locations = ctl.read_json(local_root() / "context-servers.json", {})
    paths = list(locations.get(context["id"], []))
    if not paths:
        selected = latest(context)
        if selected:
            for session in ctl.read_json(selected[0] / "tmux.json"):
                server = session["server"]
                paths.append(str(Path(f"/tmp/tmux-{os.getuid()}") / ("default" if server["default"] else "context-" + server["id"])))
        # Managed new sessions use the default server. Explicit sockets cover
        # custom-server CLI saves before their first successful checkpoint.
        paths.append(str(Path(f"/tmp/tmux-{os.getuid()}") / "default"))
    if socket_path:
        paths.append(str(socket_path))
    return [Tmux(path) for path in dict.fromkeys(paths) if Path(path).is_socket() and Tmux(path).reachable()]


def context_targets(tm, context):
    identifier = context["id"]
    owned = "#{||:#{==:#{@persistence-context}," + identifier + "},#{==:#{session_name},context-" + identifier + "}}"
    targets = [row["session_id"] for row in tm.rows("list-sessions", ["session_id"], "-f", owned)]
    # Older shells may not have acquired explicit ownership yet. Infer only
    # their local ancestors; never infer an external checkout or inspect another
    # explicitly owned session's panes.
    unowned = "#{&&:#{==:#{@persistence-context},},#{!=:#{m:context-*,#{session_name}},1}}"
    for row in tm.rows("list-sessions", ["session_id", "session_name"], "-f", unowned):
        candidate = window_close.target_context(tm, row["session_id"], row["session_name"], None, None)
        if candidate and candidate["id"] == identifier:
            targets.append(row["session_id"])
    return targets


SUPPORTED = {"vi", "vim", "view", "emacs", "man", "less", "more", "tail", "top", "htop", "irssi", "weechat", "mutt", "btop"}


def process_arguments(pane_pid, command):
    parents = {}
    for line in run(["ps", "-eo", "pid=,ppid="]).splitlines():
        pid, parent = map(int, line.split())
        parents[pid] = parent
    for pid in sorted(parents, reverse=True):
        ancestor, seen = pid, set()
        while ancestor in parents and ancestor not in seen and ancestor != pane_pid:
            seen.add(ancestor)
            ancestor = parents[ancestor]
        if ancestor != pane_pid:
            continue
        try:
            arguments = [os.fsdecode(v) for v in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if v]
            if arguments and Path(arguments[0]).name == command:
                return arguments[1:]
        except OSError:
            pass
    raise CheckpointError(f"Cannot capture foreground arguments for {command}")


def editor_ready(endpoint):
    """Fast API works even while normal RPC evaluation waits for user input."""
    import msgpack

    deadline = time.monotonic() + 3
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(3)
        connection.connect(endpoint)
        connection.sendall(msgpack.packb([0, 1, "nvim_get_mode", []], use_bin_type=True))
        replies = msgpack.Unpacker(raw=False, max_buffer_size=65536)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CheckpointError("Neovim readiness RPC timed out")
            connection.settimeout(remaining)
            data = connection.recv(4096)
            if not data:
                raise CheckpointError("Neovim readiness RPC disconnected")
            replies.feed(data)
            for reply in replies:
                if not isinstance(reply, list) or len(reply) != 4 or reply[:2] != [1, 1]:
                    raise CheckpointError("Neovim readiness RPC invalid reply")
                _, _, error, mode = reply
                if error is not None:
                    raise CheckpointError(f"Neovim readiness RPC failed: {error}")
                if not isinstance(mode, dict) or type(mode.get("blocking")) is not bool:
                    raise CheckpointError("Neovim readiness RPC invalid mode")
                if mode["blocking"]:
                    raise EditorInputBlocked("Neovim waiting for input")
                return


def editor_snapshot(endpoint):
    """A zero CLI exit status is not proof of a complete RPC reply.

    Retry only malformed successful transport replies. Native errors and schema
    mismatches remain explicit failures. All attempts share the capture deadline
    and collect only in RAM, before any checkpoint/publication writes or locks.
    """
    editor_ready(endpoint)
    expression = 'luaeval("require(\'context_persistence\').snapshot()")'
    args = ["nvim", "--server", endpoint, "--remote-expr", expression]
    deadline = time.monotonic() + 2
    detail = "empty reply"
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CheckpointError("Neovim snapshot RPC timed out; previous checkpoint retained")
        try:
            result = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                                    text=True, timeout=remaining, check=False)
        except subprocess.TimeoutExpired as exc:
            raise CheckpointError("Neovim snapshot RPC timed out; previous checkpoint retained") from exc
        if result.returncode:
            raise CheckpointError(f"Neovim snapshot RPC failed: {result.stderr.strip() or result.stdout.strip() or result.returncode}")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            detail = result.stderr.strip()[:1000] or ("empty reply" if not result.stdout.strip() else "truncated/invalid JSON reply")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CheckpointError("Neovim snapshot RPC timed out; previous checkpoint retained") from None
            if attempt < 2:
                time.sleep(min(.05, remaining))
            continue
        if (not isinstance(data, dict) or data.get("version") != 3
                or not isinstance(data.get("editor_id"), str)
                or data.get("contents_encoding") != "base64" or not isinstance(data.get("contents"), dict)):
            raise CheckpointError("Neovim session adapter identity/schema mismatch; editor session skipped")
        return data
    raise CheckpointError(f"Neovim snapshot RPC invalid after 3 attempts: {detail}; previous checkpoint retained")


def adapter_capture(tm, pane, destination, context, errors):
    local = pane.pop("local")
    if local.get("@persistence-recovery-pending") == "1" and pane["command"] != "nvim":
        raise CheckpointError(f"Pane {pane['id']} is an unresolved recovery shell; exit it and explicitly retry restoration. Previous checkpoint retained")
    command = pane["command"]
    cwd = str(decode_path(pane["cwd"], context))
    editor = local.get("@persistence-editor-socket")
    chat = local.get("@persistence-chat-socket")
    if command == "nvim":
        directory = destination / "nvim" / pane["id"]
        # A failed/old editor adapter must never veto another pane's save or close.
        try:
            if not editor:
                raise CheckpointError("Neovim session adapter absent")
            data = editor_snapshot(editor)
            if data["editor_id"] != local["@persistence-editor"]:
                raise CheckpointError("Editor identity changed during capture")
            if data.get("session") != "session.vim" or set(data["contents"]) != {"session.vim"}:
                raise CheckpointError("Invalid Neovim session snapshot")
            session = base64.b64decode(data["contents"]["session.vim"], validate=True)
        except Exception as exc:
            report(f"Editor {pane['id']}: {exc}; reopening fresh next time")
            pane.pop("editor", None)
            discarded_editor(pane, True)
            if local.get("@persistence-recovery-pending") == "1":
                tm.call("set-option", "-pu", "-t", local["pane_id"], "@persistence-recovery-pending")
            return
        if isinstance(destination, store.MemoryPath):
            for name in list(destination.tree.files):
                if name.startswith(str(directory) + "/"):
                    del destination.tree.files[name]
        data.pop("contents_encoding")
        data.pop("contents")
        (directory / "session.vim").write_bytes(session)
        write_json(directory / "editor.json", data)
        pane["editor"] = {"id": data["editor_id"], "manifest": f"nvim/{pane['id']}/editor.json"}
        discarded_editor(pane, False)
        if local.get("@persistence-recovery-pending") == "1":
            tm.call("set-option", "-pu", "-t", local["pane_id"], "@persistence-recovery-pending")
    elif command in ("opencode", "bun") or (chat and Path(chat).is_socket()):
        if not chat:
            raise CheckpointError("OpenCode TUI adapter absent; restart OpenCode before protected destruction")
        selection = chats.read_selection(Path(chat), int(local["pane_pid"]), tm.socket, local["pane_id"])
        reference = chat_library.reference(selection)
        if reference:
            pane["chat_library"] = reference
            pane.pop("chat", None)
            pane["chat_cwd"] = encode_path(selection["directory"], context)
            return
        if context:
            selection["context_root"] = context["path"]
            selection["work_root"] = context["working_directory_path"]
        directory = destination / "opencode" / pane["id"]
        data = chats.capture(selection, directory, cwd)
        pane["chat"] = f"opencode/{pane['id']}"
        pane["chat_cwd"] = encode_path(selection["directory"], context)
        for item in data["unsupported"]:
            if "draft" not in item["reason"].lower() and "in-flight" not in item["reason"].lower():
                errors.append(f"Chat {selection.get('session_id')}: {item['reason']}")
    elif command in SUPPORTED:
        arguments = process_arguments(int(local["pane_pid"]), command)
        pane["arguments"] = [encode_path(arg, context) if arg.startswith("/") else arg for arg in arguments]
    elif command not in ("bash", "zsh", "fish", "sh"):
        errors.append(f"Pane {pane['id']}: {command} will reopen as shell; process state unsupported")


def merge_retained(current, previous, old_base, destination, warnings=None):
    """Keep pre-destruction items absent from later scans; live identities win."""
    sessions = {s["id"]: s for s in current}
    for old in previous:
        new = sessions.get(old["id"])
        if new is None:
            current.append(copy.deepcopy(old))
        else:
            wins = {w["id"]: w for w in new["windows"]}
            for window in old["windows"]:
                win = wins.get(window["id"])
                if win is None:
                    new["windows"].append(copy.deepcopy(window))
                else:
                    ids = {p["id"] for p in win["panes"]}
                    missing = [p for p in window["panes"] if p["id"] not in ids]
                    if missing:
                        latest_panes = {p["id"]: p for p in win["panes"]}
                        old_ids = {p["id"] for p in window["panes"]}
                        added = [p for p in win["panes"] if p["id"] not in old_ids]
                        ordered = []
                        for pane in sorted(window["panes"], key=lambda p: p["index"]):
                            restored = copy.deepcopy(latest_panes.get(pane["id"], pane))
                            restored["index"] = pane["index"]
                            ordered.append(restored)
                        first_index = min(p["index"] for p in ordered)
                        for pane in added:
                            restored = copy.deepcopy(pane)
                            restored["index"] = first_index + len(ordered)
                            ordered.append(restored)
                        win["panes"] = ordered
                        if not added:
                            old_ids = {p["observed_id"].lstrip("%"): p["id"] for p in window["panes"]}
                            new_ids = {p["id"]: p["observed_id"].lstrip("%") for p in ordered}
                            win["layout"] = re.sub(r"(\d+x\d+,\d+,\d+,)(\d+)(?=[,}\]]|$)",
                                                   lambda m, new_ids=new_ids, old_ids=old_ids: m[1] + new_ids[old_ids[m[2]]], window["layout"])
                        else:
                            # A new pane and a retained deleted pane cannot occupy
                            # the same native leaf. Publish a coherent explicit
                            # stacked recovery arrangement, never a truncated tree.
                            width, height = map(int, re.search(r"(\d+)x(\d+)", window["layout"]).groups())
                            height = max(height, len(ordered) * 3)
                            available, y, leaves = height - len(ordered) + 1, 0, []
                            for index, pane in enumerate(ordered):
                                size = available // (len(ordered) - index)
                                leaves.append(f"{width}x{size},0,{y},{pane['observed_id'].lstrip('%')}")
                                y += size + 1
                                available -= size
                            win["layout"] = f"0000,{width}x{height},0,0[" + ",".join(leaves) + "]"
                            if warnings is not None:
                                warnings.append(f"Window {win['name']}: retained removed panes plus new panes use stacked recovery layout")
    # Recovery files are immutable and pane-keyed. Copy only absent adapter roots.
    for kind in ("nvim", "opencode"):
        for source in (old_base / kind).glob("*"):
            target = destination / kind / source.name
            if not target.exists():
                if isinstance(destination, store.MemoryPath):
                    destination.tree.copy_from(source, str(target))
                else:
                    shutil.copytree(source, target)


def normalize_layouts(sessions):
    for session in sessions:
        for window in session["windows"]:
            identities = {p["observed_id"].lstrip("%"): str(int(uuid.UUID(p["id"]).hex[:8], 16)) for p in window["panes"]}
            if len(set(identities.values())) != len(window["panes"]):
                raise CheckpointError("Pane layout identity collision; checkpoint not published")
            window["layout"] = re.sub(r"(\d+x\d+,\d+,\d+,)(\d+)(?=[,}\]]|$)",
                                      lambda m, identities=identities: m[1] + identities[m[2]], window["layout"])
            for pane in window["panes"]:
                pane["observed_id"] = "%" + identities[pane["observed_id"].lstrip("%")]


def affected_owners(captured, socket_path, operation, target_session, target_window, all_targets, group):
    target_session = target_session.removeprefix("x") if target_session else target_session
    target_window = target_window.removeprefix("x") if target_window else target_window
    on_server = [(c, tm, s) for c, tm, s in captured if tm.socket == socket_path]
    target = next((s for _, _, s in on_server if s["observed_id"] == target_session), None)
    if operation == "kill-server":
        selected = on_server
    elif operation == "kill-session":
        selected = [(c, tm, s) for c, tm, s in on_server if
                    (s["observed_id"] != target_session if all_targets else
                     s["group"] == target["group"] if group and target and target["group"] else
                     s["observed_id"] == target_session)]
    else:
        windows = {w["id"] for _, _, s in on_server for w in s["windows"]
                   if any(p["local"]["window_id"] == target_window for p in w["panes"])}
        if operation == "kill-window" and all_targets and target:
            target_windows = [w for w in target["windows"] if any(p["local"]["window_id"] == target_window for p in w["panes"])]
            windows = {w["id"] for w in target["windows"] if w not in target_windows}
            if len(target_windows) > 1:
                windows.update(w["id"] for w in target_windows)
        selected = [(c, tm, s) for c, tm, s in on_server if any(w["id"] in windows for w in s["windows"])]
    return {c["id"] if c else None for c, _, _ in selected}


@chat_library.sync_batch()
def checkpoint(reason="periodic", context_id=None, socket_path=None, operation=None,
               target_session=None, target_window=None, all_targets=False, group=False, runtime_id=None):
    # Gather application state before taking any publication lock. An exiting
    # editor can finish its own save without a helper waiting on its blocked RPC.
    # Private tab workers own their final teardown, including on older running
    # servers whose native patch predates asynchronous tab-close dispatch.
    if reason == "pre-kill" and socket_path and target_session:
        name = Tmux(socket_path).call("display-message", "-p", "-t", target_session.removeprefix("x"), "#{session_name}")
        if name.startswith(window_close.STAGING):
            return
    context = ctl.selected_context(context_id) if context_id else None
    if context_id and context is None:
        raise CheckpointError(f"Context is unavailable: {context_id}")
    contexts = ([context] if context else ctl.known_contexts() if reason == "pre-kill" or runtime_id
                else ctl.scan(check_working_directories=False))
    captured = []
    servers = (context_servers(context, socket_path) if context else
               [Tmux(socket_path)] if reason == "pre-kill" and socket_path else sockets(socket_path))
    for tm in servers:
        targets = context_targets(tm, context) if context else runtime_targets(tm, runtime_id) if runtime_id else None
        if reason == "pre-kill" and operation == "kill-session" and not all_targets:
            targets = [target_session.removeprefix("x")]
            if group:
                name = tm.call("display-message", "-p", "-t", targets[0], "#{session_group}")
                if name:
                    targets = [r["session_id"] for r in tm.rows("list-sessions", ["session_id"], "-f", "#{==:#{session_group}," + name + "}")]
        captured.extend(capture_tmux(tm, contexts, targets))
    # Cache live ownership during ordinary background discovery. Subsequent
    # selected saves do not need to discover or contact unrelated servers.
    with file_lock("context-servers"):
        locations_path = local_root() / "context-servers.json"
        locations = ctl.read_json(locations_path, {})
        for own, tm, _ in captured:
            if own:
                locations.setdefault(own["id"], [])
                if tm.socket not in locations[own["id"]]:
                    locations[own["id"]].append(tm.socket)
        write_json(locations_path, locations)
    owners = {c["id"] if c else None for c, _, _ in captured}
    if reason == "pre-kill" and operation:
        owners = affected_owners(captured, socket_path, operation, target_session, target_window, all_targets, group)
    if context_id:
        owners = {context_id}
    errors = []
    library_errors = []
    # Selected pane references save their own family through OC2's reference()
    # adapter below. Do not put whole-library maintenance ahead of unrelated
    # terminal snapshots. Closed-chat maintenance runs after those snapshots.
    for identifier in owners:
        context = next((c for c in contexts if c["id"] == identifier), None)
        try:
            lifecycle = ctl.read_json(local_root() / "lifecycle.json", {})
            if reason in ("periodic", "shutdown") and lifecycle.get(identifier or "local") == "closed":
                continue
            selected = [(tm, value) for own, tm, value in captured if (own["id"] if own else None) == identifier]
            pending = [pane["id"] for _, session in selected for window in session["windows"]
                       for pane in window["panes"] if pane.get("local", {}).get("@persistence-recovery-pending") == "1"
                       and pane["command"] != "nvim"]
            if pending:
                raise CheckpointError(f"Pane {pending[0]} is an unresolved recovery shell; exit it and explicitly retry restoration. Previous checkpoint retained")
            previous = latest(context)
            if previous:
                # Editor artifacts are disposable. Corruption in one must not
                # prevent a fresh capture; other adapters keep their guarantees.
                for name in previous[1]["artifacts"]:
                    if not name.startswith("nvim/"):
                        validate(*previous, prefix=name)
            if not selected:
                continue
            tree = store.Tree()
            destination = tree.path()
            broken_editors = set()
            # Previous adapter data lives in RAM, allowing native exporters to be
            # skipped when read-only source fingerprints and dependencies match.
            if previous:
                for artifact in previous[0].rglob("*"):
                    if artifact.is_file():
                        name = str(artifact.relative_to(previous[0]))
                        try:
                            tree.files[name] = artifact.read_bytes()
                        except Exception:
                            if not name.startswith("nvim/"):
                                raise
                            broken_editors.add(name.split("/")[1])
            warnings = [f"Context {value['orphaned_context_id']} is unavailable; session {value['name']} saved in machine-local recovery"
                        for _tm, value in selected if value.get("orphaned_context_id")]
            pane_adapters = {}
            for tm, session in selected:
                for window in session["windows"]:
                    for pane in window["panes"]:
                        key = (tm.socket, pane["id"])
                        if key in pane_adapters:
                            pane.pop("local")
                            pane.update(copy.deepcopy(pane_adapters[key]))
                        else:
                            adapter_capture(tm, pane, destination, context, warnings)
                            pane_adapters[key] = {k: copy.deepcopy(pane[k]) for k in ("editor", "chat", "chat_library", "chat_cwd", "arguments") if k in pane}
            desktop = inventory(context, selected)
            warnings.extend(desktop.pop("warnings"))
            retained_path = local_root() / f"retained-{identifier or 'local'}.json"
            retained = ctl.read_json(retained_path, {"sessions": []})
            values = [value for _, value in selected]
            normalize_layouts(values)
            # Session observations and layout checksums are not portable state.
            for session in values:
                session["observed_id"] = session["id"]
                for window in session["windows"]:
                    window["layout"] = "0000," + window["layout"].split(",", 1)[1]
            if previous and retained["sessions"]:
                old_base, _old_manifest = previous
                old = ctl.read_json(old_base / "tmux.json")
                merge_retained(values, [s for s in old if s["id"] in retained["sessions"]], old_base, destination, warnings)
                previous_desktop = ctl.read_json(old_base / "desktop.json")
                present = {w["id"] for w in desktop["windows"]}
                desktop["windows"].extend(w for w in previous_desktop["windows"]
                                          if w["session"] in retained["sessions"] and w["id"] not in present)
            if previous and (runtime_id or reason == "pre-kill" and operation == "kill-session"):
                # A targeted archive replaces only its requested sessions. Keep
                # other sessions' last saved records without contacting them.
                observed = {s["id"] for s in values}
                old_base, _ = previous
                others = [s for s in ctl.read_json(old_base / "tmux.json") if s["id"] not in observed]
                values.extend(others)
                previous_desktop = ctl.read_json(old_base / "desktop.json")
                present = {w["id"] for w in desktop["windows"]}
                other_ids = {s["id"] for s in others}
                desktop["windows"].extend(w for w in previous_desktop["windows"]
                                          if w["session"] in other_ids and w["id"] not in present)
            if previous and not desktop["windows"]:
                desktop = ctl.read_json(previous[0] / "desktop.json")
            values = window_close.filter_closed(values, context)
            desktop["windows"] = [w for w in desktop["windows"] if w["session"] in {s["id"] for s in values}]
            roots = set()
            for session in values:
                for window in session["windows"]:
                    for pane in window["panes"]:
                        if pane.get("editor"):
                            try:
                                metadata = ctl.read_json(destination / pane["editor"]["manifest"], {})
                                if not isinstance(metadata, dict):
                                    metadata = {}
                            except Exception:
                                metadata = {}
                            if (metadata.get("version") == 3 and not discarded_editor(pane)
                                    and pane["id"] not in broken_editors):
                                roots.add("nvim/" + pane["id"])
                            else:
                                pane.pop("editor")
                                pane["command"] = "nvim"
                        if pane.get("chat"):
                            roots.add(pane["chat"])
            # Prune only artifacts absent from the merged logical workspace.
            for name in list(tree.files):
                if not any(name.startswith(root + "/") for root in roots):
                    del tree.files[name]
            write_json(destination / "tmux.json", values)
            write_json(destination / "desktop.json", desktop)
            storage = checkpoint_store(context)
            with context_lock(context):
                now = latest(context)
                if (now[1] if now else None) != (previous[1] if previous else None):
                    raise CheckpointError("Checkpoint changed during capture; retry")
                if ctl.read_json(local_root() / "lifecycle.json", {}).get(identifier or "local") != lifecycle.get(identifier or "local"):
                    raise CheckpointError("Lifecycle changed during capture; retry")
                manifest, changed = storage.publish(tree, {
                    "context_id": identifier, "created_ns": time.time_ns(), "device": device(),
                    "reason": reason, "warnings": sorted(set(warnings)),
                    "migrated_from": (previous[1]["id"] if previous and previous[1]["version"] == 1
                                      else previous[1].get("migrated_from") if previous else None),
                }, previous[1] if previous and previous[1]["version"] == 2 else None,
                    discard_prefixes=("nvim/",))
                storage.remove_v1()
                # Raw server-wide dumps are unnecessary: native normalized
                # records already contain supported topology/program strategies.
                shutil.rmtree(local_root() / "resurrect", ignore_errors=True)
                if reason == "pre-kill":
                    retained["sessions"] = sorted(set(retained["sessions"]) | {s["id"] for s in values})
                    write_json(retained_path, retained)
            if changed:
                print(f"context-checkpoint: Published {identifier or 'machine-local'} {manifest['id']} ({reason})", file=sys.stderr)
            if warnings and changed:
                known = set(previous[1].get("warnings", [])) if previous else set()
                new_warnings = sorted(set(warnings) - known)
                if new_warnings:
                    notify(new_warnings)
        except (chats.ChatChangedDuringCheckpoint, EditorInputBlocked) as exc:
            if reason == "periodic":
                report(f"{identifier or 'machine-local'}: {exc}; periodic save deferred, previous checkpoint retained")
            else:
                errors.append(f"{identifier or 'machine-local'}: {exc}")
        except Exception as exc:
            errors.append(f"{identifier or 'machine-local'}: {exc}")
    # No imports here. Per-context library locks and bounded native children are
    # supplied by context_chat_library/context_chat_worker. A slow closed library
    # must not prevent other contexts' terminal snapshots from being published.
    # Pane adapters already saved the selected families. Foreground destruction
    # needs no sweep of closed histories. Periodic maintenance is dirty-driven.
    if reason == "periodic":
        chat_library.sync_dirty(contexts, errors=library_errors)
    elif reason not in ("close", "pre-kill"):
        chat_library.sync_all(contexts, hydrate=False, only=owners, errors=library_errors)
    for identifier, error in library_errors:
        if reason == "periodic" and isinstance(error, (chats.ChatChangedDuringCheckpoint, TimeoutError)):
            report(f"{identifier}: {error}; library save deferred, previous library retained")
        else:
            errors.append(f"{identifier}: {error}")
    if errors:
        notify(errors)
        raise CheckpointError("Checkpoint failed; managed destruction cancelled")


def pane_working_directory(pane, context):
    try:
        cwd = decode_path(pane["cwd"], context)
        if not cwd.is_dir():
            raise CheckpointError(f"Working directory missing: {cwd}")
        return cwd
    except Exception as exc:
        if not pane.get("editor") and pane["command"] != "nvim":
            raise
        report(f"Editor {pane['id']}: {exc}; reopening fresh in context directory")
        discarded_editor(pane, True)
        pane.pop("editor", None)
        pane["command"] = "nvim"
        return Path(context["path"]) if context else Path.home()


def pane_command(pane, base, context, errors):
    env = {}
    if context:
        env["CONTEXT_DIRECTORY"] = context["path"]
        env["CONTEXT_ID"] = context["id"]
    if pane.get("editor"):
        try:
            if discarded_editor(pane):
                raise CheckpointError("Previously failed editor session discarded")
            metadata = ctl.read_json(safe(base, pane["editor"]["manifest"]))
            if metadata.get("version") != 3 or metadata.get("session") != "session.vim":
                raise CheckpointError("Obsolete buffer recovery discarded")
        except Exception as exc:
            report(f"Editor {pane['id']}: {exc}")
            discarded_editor(pane, True)
            pane.pop("editor", None)
            return ["env", *(f"{k}={v}" for k, v in env.items()), "CONTEXT_EDITOR_FRESH=1", "nvim"]
    if isinstance(base, store.MemoryPath) and (pane.get("editor") or pane.get("chat")):
        kind = "nvim" if pane.get("editor") else "opencode"
        relative = f"{kind}/{pane['id']}"
        storage = checkpoint_store(context)
        destination = local_root() / "restore" / (context["id"] if context else "local") / relative
        storage.materialize(base / relative, destination)
        # Retain the adapter-relative layout expected by the v1 recovery reader.
        base = destination.parents[1]
    if pane.get("editor"):
        try:
            env.update(CONTEXT_EDITOR_ID=pane["editor"]["id"],
                       CONTEXT_EDITOR_RESTORE=str(safe(base, pane["editor"]["manifest"])))
            return ["env", *(f"{k}={v}" for k, v in env.items()), "nvim"]
        except Exception as exc:
            report(f"Editor {pane['id']}: {exc}; reopening fresh")
            discarded_editor(pane, True)
            pane.pop("editor", None)
            return ["env", *(f"{k}={v}" for k, v in env.items()), "CONTEXT_EDITOR_FRESH=1", "nvim"]
    if pane["command"] == "nvim":
        return ["env", *(f"{k}={v}" for k, v in env.items()), "CONTEXT_EDITOR_FRESH=1", "nvim"]
    if pane.get("chat_library"):
        try:
            sid, directory = chat_library.restore_reference(pane["chat_library"])
            return ["env", "-C", directory, *(f"{k}={v}" for k, v in env.items()), "opencode", "--session", sid]
        except Exception as exc:
            errors.append(f"Chat {pane['id']}: {exc}")
    elif pane.get("chat"):
        try:
            directory = decode_path(pane.get("chat_cwd", pane["cwd"]), context)
            sid = chats.restore(safe(base, pane["chat"]), str(directory),
                                context_root=context["path"] if context else None,
                                work_root=context["working_directory_path"] if context else None)
            return ["env", "-C", str(directory), *(f"{k}={v}" for k, v in env.items()), "opencode", *(["--session", sid] if sid else [])]
        except Exception as exc:
            errors.append(f"Chat {pane['id']}: {exc}")
    # Deliberate strategies only; never replay arbitrary shell commands/arguments.
    if pane["command"] in SUPPORTED:
        if shutil.which(pane["command"]):
            return [pane["command"], *(str(decode_path(arg, context)) if isinstance(arg, dict) else arg for arg in pane.get("arguments", []))]
        errors.append(f"Program {pane['command']} unavailable locally; pane restored as shell")
    return ["env", *(f"{k}={v}" for k, v in env.items()), os.environ.get("SHELL", "/bin/sh")]


def await_program(tm, target, pane, command):
    """Process creation is not proof that editor/chat restoration succeeded."""
    if not pane.get("editor") and not pane.get("chat") and not pane.get("chat_library"):
        # tmux returns after fork, before its child necessarily execs the launch
        # command. A scan in that gap sees "tmux" rather than the intended shell
        # or supported program; do not clear failed-restore retention yet.
        expected = Path(command[-1] if command[0] == "env" else command[0]).name
        deadline = time.monotonic() + 5
        observed = "not observed"
        while time.monotonic() < deadline:
            rows = tm.rows("list-panes", ["pane_id", "pane_current_command"], "-t", target)
            row = next((row for row in rows if row["pane_id"] == target), None)
            if row is None:
                raise CheckpointError(f"Pane {target} disappeared before process exec acknowledgement")
            observed = row["pane_current_command"]
            if observed == expected:
                return
            time.sleep(.05)
        raise CheckpointError(f"Pane {target} process readiness timed out: expected {expected}, observed {observed}")
    deadline = time.monotonic() + (3 if pane.get("editor") else 30)
    last_error = "application adapter not ready"
    while time.monotonic() < deadline:
        try:
            current = tm.rows("list-panes", ["pane_id", "pane_pid", "@persistence-editor",
                              "@persistence-editor-socket", "@persistence-chat-socket"], "-t", target)
            row = next(p for p in current if p["pane_id"] == target)
            if pane.get("editor"):
                endpoint = row["@persistence-editor-socket"]
                if row["@persistence-editor"] == pane["editor"]["id"] and endpoint and Path(endpoint).is_socket():
                    status = run(["nvim", "--server", endpoint, "--remote-expr",
                                  "get(g:, 'context_persistence_restore_status', 'loading')"], timeout=3)
                    if status in ("ready", "discarded"):
                        if status == "discarded":
                            discarded_editor(pane, True)
                        return
                    if status == "failed":
                        raise CheckpointError(f"Neovim {pane['editor']['id']} rejected recovery; see editor error")
            else:
                endpoint = row["@persistence-chat-socket"]
                expected = command[command.index("--session") + 1] if "--session" in command else None
                if endpoint and Path(endpoint).is_socket():
                    selection = chats.read_selection(Path(endpoint), int(row["pane_pid"]), tm.socket, target)
                    if selection["session_id"] == expected:
                        return
                    last_error = "OpenCode displayed a different chat than the requested snapshot"
        except CheckpointError as exc:
            if "rejected recovery" in str(exc):
                raise
            last_error = str(exc)
        except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired) as exc:
            last_error = str(exc)
        time.sleep(.1)
    raise CheckpointError(f"Pane {pane['id']} restore acknowledgement timed out: {last_error}")


def restore_tmux(base, manifest, context, errors, tm, server_id=None, acknowledgements=None):
    validate(base, manifest, "tmux.json")
    saved = window_close.filter_closed(ctl.read_json(base / "tmux.json"), context)
    if server_id is not None:
        saved = [s for s in saved if s["server"]["id"] == server_id]
    live = {}
    if tm.reachable():
        try:
            live = {s["@persistence-session-id"]: s for s in tm.rows("list-sessions", ["session_id", "session_name", "@persistence-session-id"])}
        except CheckpointError as exc:
            if "no sessions" not in str(exc):
                raise
    links, mapping = {}, {}
    for session in saved:
        try:
            existing = live.get(session["id"])
            name = session["name"]
            if not existing and any(s["session_name"] == name for s in live.values()):
                name += "-recovered-" + session["id"][:8]
                report(f"Session name conflict preserved; restoring {name}")
            session_target = existing["session_id"] if existing else None
            live_windows = {w["@persistence-window-id"]: w for w in tm.rows("list-windows", ["window_id", "@persistence-window-id"], "-t", session_target)} if existing else {}
            initial_errors = len(errors)

            def restore_one(window, session=session, name=name, live_windows=live_windows):
                nonlocal session_target
                if window["id"] in links:
                    if session_target is None:
                        if not session["group"]:
                            raise CheckpointError("Shared window in ungrouped sessions requires manual linking; preserved checkpoint")
                        session_target = tm.call("new-session", "-d", "-P", "-F", "#{session_id}", "-s", name,
                                                 "-t", links[window["id"]][0]).splitlines()[-1]
                        # Grouped sessions share all windows by native definition.
                        if window["active"]:
                            tm.call("select-window", "-t", f"{session_target}:{window['index']}")
                        return
                    existing_links = tm.rows("list-windows", ["window_id", "window_index"], "-t", session_target)
                    current_link = next((w for w in existing_links if int(w["window_index"]) == window["index"]), None)
                    if current_link is None:
                        tm.call("link-window", "-d", "-s", links[window["id"]][1], "-t", f"{session_target}:{window['index']}")
                    elif current_link["window_id"] != links[window["id"]][1]:
                        raise CheckpointError("Conflicting live shared-window link; preserved without replacement")
                    if window["active"]:
                        tm.call("select-window", "-t", f"{session_target}:{window['index']}")
                    return
                restored_panes = []
                live_window = live_windows.get(window["id"])
                win_target = live_window["window_id"] if live_window else None
                live_rows = tm.rows("list-panes", ["pane_id", "@persistence-id", "@persistence-recovery-pending"], "-t", win_target) if live_window else []
                live_panes = {p["@persistence-id"]: p["pane_id"] for p in live_rows}
                for live_pane in live_rows:
                    if live_pane["@persistence-recovery-pending"] == "1":
                        errors.append(f"Pane {live_pane['@persistence-id']}: unresolved recovery shell; exit it and explicitly retry restoration")
                if live_window and all(p["id"] in live_panes for p in window["panes"]):
                    links[window["id"]] = (session_target, win_target)
                    return
                for pane in sorted(window["panes"], key=lambda p: p["index"]):
                    if pane["id"] in live_panes:
                        restored_panes.append((pane, live_panes[pane["id"]]))
                        continue
                    pane_errors = len(errors)
                    try:
                        if acknowledgements is not None:
                            # Construct visible backing topology before imports,
                            # external cwd checks, or application initialization.
                            cwd = Path(context["path"]) if context else Path.home()
                            command = ["/bin/sh", "-c", "printf 'Restoring saved pane...\\n'; exec sleep 2147483647"]
                        else:
                            validate_pane(base, manifest, pane)
                            cwd = pane_working_directory(pane, context)
                            command = pane_command(pane, base, context, errors)
                    except Exception as exc:
                        errors.append(f"Pane {pane['id']}: {exc}; starting recovery shell")
                        cwd = Path(context["cwd"]) if context else Path.home()
                        command = [os.environ.get("SHELL", "/bin/sh")]
                    if session_target is None:
                        output = tm.call("new-session", "-d", "-P", "-F", "#{session_id} #{window_id} #{pane_id}",
                                         "-s", name, "-c", cwd, *command)
                        session_target, win_target, target = output.splitlines()[-1].split()
                        tm.call("set-option", "-s", "@persistence-server-id", session["server"]["id"])
                        current_index = int(tm.call("display-message", "-p", "-t", win_target, "#{window_index}"))
                        if current_index != window["index"]:
                            tm.call("move-window", "-s", win_target, "-t", f"{session_target}:{window['index']}")
                    elif not restored_panes and not live_window:
                        win_target, target = tm.call("new-window", "-d", "-P", "-F", "#{window_id} #{pane_id}",
                                                    "-t", f"{session_target}:{window['index']}", "-c", cwd, *command).splitlines()[-1].split()
                    else:
                        split_target = restored_panes[-1][1] if restored_panes else win_target
                        target = tm.call("split-window", "-d", "-P", "-F", "#{pane_id}", "-t", split_target,
                                         "-c", cwd, *command).splitlines()[-1]
                        tm.call("select-layout", "-t", win_target, "tiled")
                    tm.call("set-option", "-p", "-t", target, "@persistence-id", pane["id"])
                    if len(errors) == pane_errors:
                        if acknowledgements is not None:
                            # Pending is durable before visibility; a periodic
                            # capture must not replace a still-loading recovery.
                            tm.call("set-option", "-p", "-t", target, "@persistence-recovery-pending", "1")
                            acknowledgements.append((session["id"], tm, target, pane, None, base, context, manifest))
                        else:
                            try:
                                acknowledge_program(tm, target, pane, command, base, context)
                            except Exception as exc:
                                errors.append(str(exc))
                    if len(errors) != pane_errors:
                        # A visible shell is an honest recovery failure, not a
                        # replacement for the saved editor/chat. Never let its
                        # later periodic scan erase the failed item's snapshot.
                        tm.call("set-option", "-p", "-t", target, "@persistence-recovery-pending", "1")
                    tm.call("select-pane", "-t", target, "-T", pane["title"])
                    restored_panes.append((pane, target))
                if not restored_panes:
                    return
                links[window["id"]] = (session_target, win_target)
                tm.call("set-option", "-w", "-t", win_target, "@persistence-window-id", window["id"])
                tm.call("rename-window", "-t", win_target, window["name"])
                # rename-window disables automatic naming. Restore its saved mode
                # afterwards; old snapshots may have frozen tmux's transient label.
                automatic = window.get("automatic_rename", False) or window["name"] == "[tmux]"
                tm.call("set-option", "-w", "-t", win_target, "automatic-rename", "on" if automatic else "off")
                # select-layout assigns leaves in native pane-index order. Restore
                # that order first, including missing panes added to live windows.
                for index, (_, wanted) in enumerate(restored_panes):
                    ordered = tm.rows("list-panes", ["pane_id", "pane_index"], "-t", win_target)
                    current = sorted(ordered, key=lambda p: int(p["pane_index"]))[index]["pane_id"]
                    if current != wanted:
                        tm.call("swap-pane", "-d", "-s", wanted, "-t", current)
                # Native layouts use local pane numbers; replace every leaf ID and checksum.
                pane_ids = {p["observed_id"].lstrip("%"): target.lstrip("%") for p, target in restored_panes}
                layout = window["layout"].split(",", 1)[1]
                layout = re.sub(r"(\d+x\d+,\d+,\d+,)(\d+)(?=[,}\]]|$)",
                                lambda m: m[1] + pane_ids[m[2]], layout)
                checksum = 0
                for char in layout.encode():
                    checksum = ((checksum >> 1) | ((checksum & 1) << 15)) + char
                    checksum &= 0xffff
                tm.call("select-layout", "-t", win_target, f"{checksum:04x},{layout}")
                active = next((target for p, target in restored_panes if p["active"]), restored_panes[0][1])
                tm.call("select-pane", "-t", active)
                if window["zoom"]:
                    tm.call("resize-pane", "-Z", "-t", active)
                if window["active"]:
                    tm.call("select-window", "-t", win_target)
            for window in sorted(session["windows"], key=lambda w: w["index"]):
                try:
                    restore_one(window)
                except Exception as exc:
                    errors.append(f"Window {window['name']} ({session['name']}): {exc}")
            if session_target:
                tm.call("set-option", "-t", session_target, "@persistence-session-id", session["id"])
                if context:
                    tm.call("set-option", "-t", session_target, "@persistence-context", context["id"])
                    tm.call("set-environment", "-t", session_target, "CONTEXT_DIRECTORY", context["path"])
                    tm.call("set-environment", "-t", session_target, "CONTEXT_ID", context["id"])
                    tm.set_working_directory(session_target, context["cwd"])
                mapping[session["id"]] = {"socket": tm.socket, "target": session_target,
                                           "complete": len(errors) == initial_errors}
        except Exception as exc:
            errors.append(f"Session {session['name']}: {exc}")
    return mapping


def acknowledge_program(tm, target, pane, command, base, context):
    try:
        await_program(tm, target, pane, command)
    except Exception as exc:
        if not pane.get("editor"):
            raise
        # Do not kill a live editor or retain an unresolved-recovery marker.
        report(f"Editor {pane['id']}: {exc}; saved session discarded")
        discarded_editor(pane, True)
    if isinstance(base, store.MemoryPath):
        for kind in ("nvim", "opencode"):
            shutil.rmtree(local_root() / "restore" / (context["id"] if context else "local") / kind / pane["id"], ignore_errors=True)


def finish_acknowledgements(pending, mapping, errors):
    # All terminal windows have already been shown. Independent readiness waits
    # share a bounded pool instead of serial 30-second deadlines per pane.
    def complete(record):
        sid, tm, target, pane, command, base, context = record[:7]
        if command is None:
            issues = []
            try:
                validate_pane(base, record[7], pane)
                cwd = pane_working_directory(pane, context)
                command = pane_command(pane, base, context, issues)
                if issues:
                    raise CheckpointError("; ".join(issues))
                tm.call("respawn-pane", "-k", "-t", target, "-c", cwd, *command)
            except Exception:
                # A failed import leaves a usable, explicitly pending recovery
                # shell rather than an eternal loading placeholder.
                cwd = context["path"] if context else str(Path.home())
                tm.call("respawn-pane", "-k", "-t", target, "-c", cwd, os.environ.get("SHELL", "/bin/sh"))
                raise
        acknowledge_program(tm, target, pane, command, base, context)
        tm.call("set-option", "-pu", "-t", target, "@persistence-recovery-pending")
        return sid

    with ThreadPoolExecutor(max_workers=16) as pool:
        jobs = {pool.submit(complete, record): record[0] for record in pending}
        for job in as_completed(jobs):
            try:
                job.result()
            except Exception as exc:
                sid = jobs[job]
                if sid in mapping:
                    mapping[sid]["complete"] = False
                errors.append(str(exc))


def restore(context, runtime_id=None, tm=None, windows=True):
    # Serialize reconstruction against publication for this context only. Other
    # contexts' lifecycle updates must not wait for editor/chat/window startup.
    with context_lock(context):
        errors, warnings = [], []
        try:
            selected = latest(context)
            if selected is None:
                return False
            base, manifest = selected
            warnings.extend(manifest.get("warnings", []))
            validate(base, manifest, "tmux.json")
            saved = window_close.filter_closed(ctl.read_json(base / "tmux.json"), context)
            retention_path = local_root() / f"retained-{context['id'] if context else 'local'}.json"
            retained = ctl.read_json(retention_path, {"sessions": []})
            retained["sessions"] = sorted(set(retained["sessions"]) | {s["id"] for s in saved})
            ctl.atomic_json(retention_path, retained)
            mapping = {}
            acknowledgements = []
            if tm is not None:
                mapping.update(restore_tmux(base, manifest, context, errors, tm, acknowledgements=acknowledgements))
            else:
                servers = {s["server"]["id"]: s["server"] for s in saved}
                for identity, server in servers.items():
                    path = Path(f"/tmp/tmux-{os.getuid()}")
                    path.mkdir(mode=0o700, exist_ok=True)
                    target = Tmux(path / ("default" if server["default"] else "context-" + identity))
                    mapping.update(restore_tmux(base, manifest, context, errors, target, identity, acknowledgements=acknowledgements))
            failed_windows = set()
            if windows and runtime_id:
                validate(base, manifest, "desktop.json")
                desktop = ctl.read_json(base / "desktop.json")
                failed_windows = restore_windows(desktop, mapping, context, runtime_id, errors, warnings)
            finish_acknowledgements(acknowledgements, mapping, errors)
            complete = {sid for sid, result in mapping.items() if result.get("complete") and sid not in failed_windows}
            retained["sessions"] = [sid for sid in retained["sessions"] if sid not in complete]
            ctl.atomic_json(retention_path, retained)
        except Exception as exc:
            errors.append(str(exc))
        notify([*errors, *warnings])
        return True


def restore_windows(desktop, mapping, context, runtime_id, errors, warnings=None):
    warnings = warnings if warnings is not None else errors
    failed = set()
    monitors = json.loads(run(["hyprctl", "-j", "monitors"]))
    if not monitors:
        raise CheckpointError("No monitors available")
    names = {m["name"] for m in monitors}
    focused = None
    for window in sorted(desktop["windows"], key=lambda w: w["order"]):
        try:
            attachment = mapping.get(window["session"])
            if not attachment:
                errors.append(f"Terminal {window['id']}: no backing session")
                failed.add(window["session"])
                continue
            cls = f"context-terminal-{window['id']}"
            observed = ctl.read_json(local_root() / f"windows-{ctl.signature()}.json", {})
            existing = next((c for c in ctl.clients() if c.get("class") == cls
                             or observed.get(f"{c['address']}:{c['pid']}") == window["id"]), None)
            if existing is None:
                ctl.spawn(["kitty", "--class", cls, "--directory", context["cwd"] if context else str(Path.home()),
                           "tmux", "-S", attachment["socket"], "attach-session", "-t", attachment["target"]])
                deadline = time.monotonic() + 10
                while existing is None and time.monotonic() < deadline:
                    time.sleep(.05)
                    existing = next((c for c in ctl.clients() if c.get("class") == cls), None)
                if existing is None:
                    raise CheckpointError("Kitty window did not map")
            monitor = window["monitor"] if window["monitor"] in names else min(names)
            if monitor != window["monitor"]:
                warnings.append(f"Terminal {window['id']}: monitor {window['monitor']} unavailable; using {monitor}")
            placement = dict(window, monitor=monitor, address=existing["address"])
            ctl.evaluate("require('context-terminals').place(" + ctl.lua_string(runtime_id) + ","
                         + lua_value(placement) + ")")
            if window["focused"]:
                focused = existing["address"]
        except Exception as exc:
            errors.append(f"Terminal {window['id']}: {exc}")
            failed.add(window["session"])
    if desktop.get("desktop"):
        view = {}
        for output in desktop["desktop"]:
            monitor = output["monitor"] if output["monitor"] in names else min(names)
            # Multiple missing source outputs collapse deterministically to one
            # destination view rather than passing duplicate monitor entries.
            view.setdefault(monitor, {"monitor": monitor, "slot": output.get("slot", 1), "role": output.get("role")})
        ctl.evaluate("require('context-terminals').view(" + ctl.lua_string(runtime_id) + "," + lua_value(list(view.values())) + ")")
    if any(not w["floating"] for w in desktop["windows"]):
        warnings.append("Tiled terminal order/size approximated: compositor exposes no native tiling-tree snapshot API")
    if focused:
        ctl.evaluate("if require('sessions').state().active == " + ctl.lua_string(runtime_id)
                     + " then assert(hl.dispatch(hl.dsp.focus({window=" + ctl.lua_string("address:" + focused) + "})).ok) end")
    return failed


def lua_value(value):
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return ctl.lua_string(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "{" + ",".join(lua_value(item) for item in value) + "}"
    return "{" + ",".join("[" + lua_value(k) + "]=" + lua_value(v) for k, v in value.items()) + "}"


def doctor():
    """Diagnose running processes; installing a new client cannot upgrade servers."""
    issues = []
    for tm in sockets():
        try:
            try:
                native = tm.call("show-options", "-s", "-v", "@persistence-native")
            except CheckpointError:
                native = ""
            if native != "1":
                issues.append(f"{tm.socket}: old tmux server; restart safely after saving live work")
            for pane in tm.rows("list-panes", ["pane_id", "pane_current_command", "@persistence-editor-socket", "@persistence-chat-socket"], "-a"):
                command = pane["pane_current_command"]
                key = "@persistence-editor-socket" if command == "nvim" else "@persistence-chat-socket"
                if command in ("nvim", "opencode") and (not pane[key] or not Path(pane[key]).is_socket()):
                    issues.append(f"{tm.socket} {pane['pane_id']}: restart {command} to load recovery adapter")
        except (CheckpointError, OSError, ValueError) as exc:
            issues.append(str(exc))
    try:
        value = run(["busctl", "get-property", "org.freedesktop.login1", "/org/freedesktop/login1",
                     "org.freedesktop.login1.Manager", "InhibitDelayMaxUSec"])
        if int(value.split()[-1]) < 95_000_000:
            issues.append("Running logind shutdown delay below 95s; deploy system configuration and reload logind")
    except (CheckpointError, ValueError, OSError) as exc:
        issues.append(f"Cannot verify logind shutdown delay: {exc}")
    print(json.dumps({"ready": not issues, "issues": issues}, indent=2))
    return not issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["save", "pre-kill", "close-tab", "retry-close", "restore", "verify", "doctor"])
    parser.add_argument("--request")
    parser.add_argument("--socket")
    parser.add_argument("--context")
    parser.add_argument("--reason", default="manual")
    parser.add_argument("--no-windows", action="store_true")
    parser.add_argument("--operation", choices=["kill-server", "kill-session", "kill-window", "kill-pane"])
    parser.add_argument("--target-session")
    parser.add_argument("--target-window")
    parser.add_argument("--target-pane")
    parser.add_argument("--all", type=int, default=0)
    parser.add_argument("--group", type=int, default=0)
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            return 0 if doctor() else 1
        context = ctl.selected_context(args.context) if args.context else None
        if args.context and context is None:
            raise CheckpointError(f"Context is unavailable: {args.context}")
        if args.command == "retry-close":
            window_close.retry_close(args.request)
        elif args.command == "close-tab":
            window_close.close_tab(args.socket, args.operation, args.target_session, args.target_window,
                                   args.target_pane, bool(args.all))
        elif args.command in ("save", "pre-kill"):
            checkpoint("pre-kill" if args.command == "pre-kill" else args.reason, args.context, args.socket,
                       args.operation, args.target_session, args.target_window, bool(args.all), bool(args.group))
        elif args.command == "verify":
            selected = latest(context)
            if selected is None:
                raise CheckpointError("No checkpoint")
            validate(*selected)
        else:
            restore(context, tm=Tmux(args.socket) if args.socket else None, windows=not args.no_windows)
        return 0
    except Exception as exc:
        notify([str(exc)])
        return 1


if __name__ == "__main__":
    sys.exit(main())
