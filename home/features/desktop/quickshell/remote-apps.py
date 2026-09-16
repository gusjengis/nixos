#!/usr/bin/env python3
"""Small JSON/SSH bridge for the Quickshell Waypipe launcher."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile

ICON_LIMIT = 256 * 1024
SSH_OPTIONS = [
    "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
    "-o", "ConnectTimeout=4", "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=1",
]


def validate_host(value):
    if len(value) > 253 or not all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
        for label in value.split(".")
    ):
        raise ValueError("invalid DNS host")
    return value


def validate_id(value):
    if (not value.endswith(".desktop") or len(value.encode()) > 255
            or value.startswith("-") or "/" in value or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or value == ".desktop"):
        raise ValueError("invalid desktop ID")
    return value


def ssh_command(host, *args):
    validate_host(host)
    # Static shell setup only; all remote command arguments are shell-quoted.
    remote = (
        'export PATH="$HOME/.nix-profile/bin:/etc/profiles/per-user/$USER/bin:$PATH"; '
        'export XDG_DATA_DIRS="${XDG_DATA_DIRS:-$HOME/.nix-profile/share:'
        '/etc/profiles/per-user/$USER/share:/run/current-system/sw/share:'
        '/usr/local/share:/usr/share}"; '
        "exec " + shlex.join(["quickshell-remote-apps", *args])
    )
    # Waypipe executes a program, not shell syntax; keep setup inside its session.
    return ["ssh", *SSH_OPTIONS, host, shlex.join(["sh", "-c", remote])]


def capture_metadata(command, timeout):
    process = None
    cancelled = False
    finished = False

    def cancel(signum, _frame):
        nonlocal cancelled
        cancelled = True
        # During Popen, defer interruption until we own the child's PID.
        if process is not None:
            raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, cancel)
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, start_new_session=True)
        if cancelled:
            raise SystemExit(128 + signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=timeout)
        finished = True
        result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        result.check_returncode()
        return result
    finally:
        # A repeated cancellation must not interrupt termination or reaping.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            if process is not None:
                if not finished:
                    for sig in (signal.SIGTERM, signal.SIGKILL):
                        try:
                            os.killpg(process.pid, sig)
                        except ProcessLookupError:
                            pass
                        if sig == signal.SIGTERM:
                            try:
                                process.wait(timeout=0.5)
                            except subprocess.TimeoutExpired:
                                pass
                        else:
                            process.wait()
                process.stdout.close()
                process.stderr.close()
        finally:
            signal.signal(signal.SIGTERM, previous)


def hosts(status):
    result = []
    for peer in (status.get("Peer") or {}).values():
        if peer.get("OS") != "linux" or not peer.get("DNSName"):
            continue
        host = peer["DNSName"].rstrip(".")
        try:
            validate_host(host)
        except ValueError:
            continue
        result.append({"id": host, "name": host.split(".")[0],
                       "description": f"{host} ({'online' if peer.get('Online') else 'offline'})",
                       "icon": ""})
    return sorted(result, key=lambda item: (item["name"].casefold(), item["id"]))


def desktop_files():
    home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local/share")
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    seen = set()
    for root in [home, *dirs.split(":")]:
        if not os.path.isabs(root):
            continue
        applications = Path(root) / "applications"
        for path in sorted(applications.rglob("*.desktop")):
            desktop_id = str(path.relative_to(applications)).replace(os.sep, "-")
            if desktop_id in seen:
                continue
            # Even Hidden, invalid and failed TryExec entries mask lower roots.
            seen.add(desktop_id)
            try:
                validate_id(desktop_id)
            except ValueError:
                continue
            yield desktop_id, path


def gi_modules():
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    return Gio, GLib


def visible_app(Gio, path):
    try:
        app = Gio.DesktopAppInfo.new_from_filename(str(path))
    except TypeError:
        # PyGObject reports a NULL constructor for invalid/failed TryExec entries.
        return None
    if app and not app.get_is_hidden() and not app.get_nodisplay() and app.should_show():
        return app
    return None


def icon_theme():
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        # A standalone theme needs no Gdk screen or display connection.
        theme = Gtk.IconTheme.new()
        theme.set_custom_theme(os.environ.get("QUICKSHELL_REMOTE_ICON_THEME", "Adwaita"))
        return theme
    except (ImportError, ValueError, RuntimeError):
        return None


def icon_data(path):
    if not path:
        return None
    path = Path(path)
    mime = {".png": "image/png", ".svg": "image/svg+xml", ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(path.suffix.lower())
    if not mime:
        return None
    try:
        if not path.is_file() or path.stat().st_size > ICON_LIMIT:
            return None
        with path.open("rb") as stream:
            data = stream.read(ICON_LIMIT + 1)
        if not data or len(data) > ICON_LIMIT:
            return None
    except OSError:
        return None
    return f"data:{mime};base64," + base64.b64encode(data).decode("ascii")


def export_apps():
    Gio, _ = gi_modules()
    theme = icon_theme()
    result = []
    for desktop_id, path in desktop_files():
        app = visible_app(Gio, path)
        if not app:
            continue
        icon = app.get_icon()
        name, filename = "", None
        if isinstance(icon, Gio.ThemedIcon):
            names = icon.get_names()
            name = names[0] if names else ""
            if theme:
                info = theme.choose_icon(names, 64, 0)
                if info:
                    filename = info.get_filename()
        elif isinstance(icon, Gio.FileIcon):
            filename = icon.get_file().get_path()
        item = {"id": desktop_id, "name": app.get_display_name(),
                "description": app.get_description() or "", "icon": name}
        data = icon_data(filename)
        if data:
            item["iconData"] = data
        result.append(item)
    return sorted(result, key=lambda item: (item["name"].casefold(), item["id"]))


def direct_app(Gio, GLib, path):
    keyfile = GLib.KeyFile()
    keyfile.load_from_file(str(path), GLib.KeyFileFlags.NONE)
    keyfile.set_boolean("Desktop Entry", "DBusActivatable", False)
    # new_from_keyfile has no filename: retain the original %k field semantics.
    command = keyfile.get_string("Desktop Entry", "Exec")
    quoted_path = '"' + re.sub(r'([\\"`$])', r'\\\1', str(path).replace("%", "%%")) + '"'
    command = re.sub(r"%%|%k", lambda m: quoted_path if m[0] == "%k" else m[0], command)
    keyfile.set_string("Desktop Entry", "Exec", command)
    app = Gio.DesktopAppInfo.new_from_keyfile(keyfile)
    if not app:
        raise ValueError("desktop entry has no usable Exec")
    return app


def run_app(desktop_id):
    validate_id(desktop_id)
    Gio, GLib = gi_modules()
    for candidate, path in desktop_files():
        if candidate != desktop_id:
            continue
        if not visible_app(Gio, path):
            raise ValueError("desktop entry is hidden or unavailable")
        app = direct_app(Gio, GLib, path)
        pids = []
        app.launch_uris_as_manager(
            [], Gio.AppLaunchContext(), GLib.SpawnFlags.DO_NOT_REAP_CHILD,
            None, None, lambda _app, pid, _data: pids.append(pid), None,
        )
        if not pids:
            raise RuntimeError("desktop entry did not spawn a process")
        # Keep the SSH/Waypipe session alive for the application's lifetime.
        codes = [os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]) for pid in pids]
        return next((code if code > 0 else 128 - code for code in codes if code), 0)
    raise ValueError("desktop ID not found")


def start_app(host, desktop_id):
    state = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    if not state.is_absolute():
        raise ValueError("XDG_STATE_HOME must be absolute")
    directory = state / "quickshell/remote-apps"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    fd, log = tempfile.mkstemp(prefix="launch-", suffix=".log", dir=directory)
    with os.fdopen(fd, "ab") as output:
        # Use this interpreter/script, not PATH lookup; wrapper environment is inherited.
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "launch", host, desktop_id,
             "--failure-log", log],
            stdin=subprocess.DEVNULL, stdout=output, stderr=output,
            start_new_session=True, close_fds=True, cwd="/", env=os.environ.copy(),
            umask=0o077,
        )
    return 0


def launch_app(host, desktop_id, failure_log=None):
    try:
        # Connection/liveness are bounded by SSH; app lifetime is unlimited.
        code = subprocess.run(["waypipe", "--no-gpu", "--xwls",
                               *ssh_command(host, "run", desktop_id)]).returncode
    except OSError as error:
        if not failure_log:
            raise
        print(f"quickshell-remote-apps: {error}", file=sys.stderr, flush=True)
        code = 1
    if code and failure_log:
        sys.stdout.flush()
        sys.stderr.flush()
        detail = ""
        try:
            with open(failure_log, "rb") as log:
                log.seek(max(0, os.fstat(log.fileno()).st_size - 4096))
                lines = log.read(4096).decode("utf-8", errors="replace").splitlines()
            detail = next((line for line in reversed(lines) if line.strip()), "")
            detail = " ".join("".join(c for c in detail if c.isprintable()).split())[:300]
        except OSError:
            pass
        message = f"{desktop_id} on {host} failed (exit {code})"
        if detail:
            message += f": {detail}"
        message += f". Log: {failure_log}"
        try:
            subprocess.run(["qs", "ipc", "call", "launcher", "failure", message],
                           stdin=subprocess.DEVNULL, check=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as error:
            print(f"quickshell-remote-apps: failure notification unavailable: {error}",
                  file=sys.stderr, flush=True)
    return code


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("hosts")
    commands.add_parser("export")
    commands.add_parser("list").add_argument("host", type=validate_host)
    launch = commands.add_parser("launch")
    launch.add_argument("host", type=validate_host)
    launch.add_argument("id", type=validate_id)
    launch.add_argument("--failure-log", help=argparse.SUPPRESS)
    start = commands.add_parser("start", help="launch detached; report failures through Quickshell IPC")
    start.add_argument("host", type=validate_host)
    start.add_argument("id", type=validate_id)
    commands.add_parser("run").add_argument("id", type=validate_id)
    args = parser.parse_args(argv)
    try:
        if args.command == "hosts":
            status = capture_metadata(["tailscale", "status", "--json"], timeout=10)
            result = hosts(json.loads(status.stdout))
        elif args.command == "export":
            result = export_apps()
        elif args.command == "list":
            remote = capture_metadata(ssh_command(args.host, "export"), timeout=30)
            result = json.loads(remote.stdout)
            if not isinstance(result, list):
                raise ValueError("remote export must be a JSON array")
            for item in result:
                if not isinstance(item, dict) or not all(
                    isinstance(item.get(key), str) for key in ("id", "name", "description", "icon")
                ):
                    raise ValueError("invalid remote app metadata")
                validate_id(item["id"])
                if "iconData" in item and (
                    not isinstance(item["iconData"], str)
                    or len(item["iconData"]) > 4 * ((ICON_LIMIT + 2) // 3) + 64
                    or not re.fullmatch(r"data:image/(?:png|svg\+xml|jpeg|webp);base64,[A-Za-z0-9+/=]+", item["iconData"])
                ):
                    raise ValueError("invalid remote icon data")
        elif args.command == "launch":
            return launch_app(args.host, args.id, args.failure_log)
        elif args.command == "start":
            return start_app(args.host, args.id)
        else:
            return run_app(args.id)
        print(json.dumps(result, ensure_ascii=True))
        return 0
    except Exception as error:
        # CLI boundary also covers lazily imported GLib.Error without a traceback.
        print(f"quickshell-remote-apps: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr.strip(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
