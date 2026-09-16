import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("remote_apps", Path(__file__).with_name("remote-apps.py"))
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class BackendTests(unittest.TestCase):
    def test_host_validation(self):
        for host in ("node", "node.tail123.ts.net", "100.64.0.1"):
            self.assertEqual(backend.validate_host(host), host)
        for host in ("", "-oProxyCommand=oops", "user@host", "host;id", "host\n", "a..b", "a/../b"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                backend.validate_host(host)

    def test_id_validation_and_shell_quoting(self):
        desktop_id = "weird '$(touch injected); app.desktop"
        self.assertEqual(backend.validate_id(desktop_id), desktop_id)
        command = backend.ssh_command("node.tail.ts.net", "run", desktop_id)
        self.assertEqual(command[-2], "node.tail.ts.net")
        remote = shlex.split(command[-1])
        self.assertEqual(remote[:2], ["sh", "-c"])
        self.assertEqual(len(remote), 3)
        self.assertEqual(shlex.split(remote[2].split("; exec ", 1)[1]),
                         ["quickshell-remote-apps", "run", desktop_id])
        self.assertIn("BatchMode=yes", command)
        self.assertIn("StrictHostKeyChecking=accept-new", command)
        for value in ("../foo.desktop", "/foo.desktop", "foo", "-x.desktop", "x\n.desktop", ".desktop"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                backend.validate_id(value)

    def test_hosts_include_offline_linux_dns_only(self):
        result = backend.hosts({"Peer": {
            "a": {"OS": "linux", "DNSName": "a.ts.net.", "HostName": "A", "Online": True},
            "b": {"OS": "linux", "DNSName": "b.ts.net.", "Online": False},
            "c": {"OS": "windows", "DNSName": "c.ts.net."},
            "d": {"OS": "linux", "DNSName": ""},
            "e": {"OS": "linux", "DNSName": "bad;host"},
        }})
        self.assertEqual([item["id"] for item in result], ["a.ts.net", "b.ts.net"])
        self.assertEqual([item["name"] for item in result], ["a", "b"])
        self.assertIn("offline", result[1]["description"])
        self.assertTrue(all(item["icon"] == "" for item in result))

    def test_xdg_precedence_includes_hidden_masks_and_nested_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            user, system = Path(tmp) / "user", Path(tmp) / "system"
            for root in (user, system):
                (root / "applications").mkdir(parents=True)
                (root / "applications/masked.desktop").write_text("[Desktop Entry]\nHidden=true\n")
            (system / "applications/vendor").mkdir()
            (system / "applications/vendor/app.desktop").write_text("invalid")
            with patch.dict(os.environ, XDG_DATA_HOME=str(user), XDG_DATA_DIRS=str(system)):
                entries = dict(backend.desktop_files())
            self.assertEqual(entries["masked.desktop"], user / "applications/masked.desktop")
            self.assertEqual(entries["vendor-app.desktop"], system / "applications/vendor/app.desktop")

    def test_icon_data_bounded_and_never_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            icon = Path(tmp) / "$(touch injected).svg"
            content = b'<svg xmlns="http://www.w3.org/2000/svg"/>'
            icon.write_bytes(content)
            with patch.object(subprocess, "run", side_effect=AssertionError("unexpected execution")):
                data = backend.icon_data(icon)
            self.assertEqual(base64.b64decode(data.split(",", 1)[1]), content)
            icon.write_bytes(b"x" * (backend.ICON_LIMIT + 1))
            self.assertIsNone(backend.icon_data(icon))
            self.assertIsNone(backend.icon_data(Path(tmp) / "missing.png"))

    def test_list_contract_and_timeout(self):
        apps = [{"id": "app.desktop", "name": "App", "description": "$(no execution)", "icon": "app"}]
        with patch.object(backend, "capture_metadata", return_value=subprocess.CompletedProcess([], 0, json.dumps(apps))) as run:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(backend.main(["list", "node"]), 0)
            self.assertEqual(json.loads(output.getvalue()), apps)
            self.assertEqual(run.call_args.kwargs["timeout"], 30)
        with patch.object(backend, "capture_metadata", side_effect=subprocess.TimeoutExpired("ssh", 30)):
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(backend.main(["list", "node"]), 1)
                self.assertEqual(output.getvalue(), "")

    def test_capture_success_errors_and_signal_restoration(self):
        previous = signal.getsignal(signal.SIGTERM)
        result = backend.capture_metadata([sys.executable, "-c", "print('[]')"], timeout=3)
        self.assertEqual(result.stdout, "[]\n")
        with self.assertRaises(subprocess.CalledProcessError) as error:
            backend.capture_metadata([sys.executable, "-c",
                                      "import sys; print('failure', file=sys.stderr); sys.exit(7)"], timeout=3)
        self.assertEqual(error.exception.returncode, 7)
        self.assertEqual(error.exception.stderr, "failure\n")
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_capture_timeout_kills_and_reaps_child(self):
        children = []
        popen = subprocess.Popen

        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            return child

        previous = signal.getsignal(signal.SIGTERM)
        with patch.object(subprocess, "Popen", side_effect=spawn):
            with self.assertRaises(subprocess.TimeoutExpired):
                backend.capture_metadata([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)
        child = children[0]
        with self.assertRaises(ChildProcessError):
            os.waitpid(child.pid, os.WNOHANG)
        self.assertIsNotNone(child.returncode)
        self.assertTrue(child.stdout.closed)
        self.assertTrue(child.stderr.closed)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_sigterm_during_spawn_defers_until_child_can_be_reaped(self):
        children = []
        popen = subprocess.Popen

        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs)
            children.append(child)
            signal.raise_signal(signal.SIGTERM)
            return child

        previous = signal.getsignal(signal.SIGTERM)
        with patch.object(subprocess, "Popen", side_effect=spawn):
            with self.assertRaises(SystemExit) as error:
                backend.capture_metadata([sys.executable, "-c", "import time; time.sleep(30)"], timeout=3)
        self.assertEqual(error.exception.code, 143)
        with self.assertRaises(ChildProcessError):
            os.waitpid(children[0].pid, os.WNOHANG)
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous)

    def test_metadata_sigterm_kills_group_and_reaps_child(self):
        # Keep the cancelled helper alive after SystemExit to inspect its reaping.
        runner = (
            "import importlib.util, os, pathlib, sys, time\n"
            "spec = importlib.util.spec_from_file_location('backend', sys.argv[1])\n"
            "backend = importlib.util.module_from_spec(spec); spec.loader.exec_module(backend)\n"
            "try:\n"
            "    backend.main(sys.argv[2:])\n"
            "except SystemExit as error:\n"
            "    pid = int(pathlib.Path(os.environ['CHILD_PID']).read_text())\n"
            "    try:\n"
            "        os.waitpid(pid, os.WNOHANG)\n"
            "    except ChildProcessError:\n"
            "        print('reaped', flush=True)\n"
            "    sys.exit(error.code)\n"
        )
        for command in (["hosts"], ["list", "node"]):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                helper = root / ("tailscale" if command == ["hosts"] else "ssh")
                helper.write_text(
                    f"#!{sys.executable}\n"
                    "import os, pathlib, signal, time\n"
                    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
                    "pathlib.Path(os.environ['CHILD_PID']).write_text(str(os.getpid()))\n"
                    "if os.fork() == 0:\n"
                    "    signal.signal(signal.SIGTERM, lambda *_: "
                    "pathlib.Path(os.environ['GROUP_SIGNAL']).touch())\n"
                    "    pathlib.Path(os.environ['READY']).touch()\n"
                    "    while True: time.sleep(1)\n"
                    "while True: time.sleep(1)\n"
                )
                helper.chmod(0o700)
                env = dict(os.environ, PATH=tmp, CHILD_PID=str(root / "pid"),
                           GROUP_SIGNAL=str(root / "group-signal"), READY=str(root / "ready"))
                with subprocess.Popen([sys.executable, "-B", "-c", runner, backend.__file__, *command],
                                      env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as parent:
                    try:
                        deadline = time.monotonic() + 3
                        while not (root / "ready").exists() and time.monotonic() < deadline:
                            time.sleep(0.01)
                        self.assertTrue((root / "ready").exists())
                        pid = int((root / "pid").read_text())
                        parent.terminate()
                        stdout, stderr = parent.communicate(timeout=3)
                        self.assertEqual(parent.returncode, 143)
                        self.assertEqual(stdout, "reaped\n")
                        self.assertEqual(stderr, "")
                        self.assertTrue((root / "group-signal").exists())
                        with self.assertRaises(ProcessLookupError):
                            os.kill(pid, 0)
                    finally:
                        if (root / "pid").exists():
                            try:
                                os.killpg(int((root / "pid").read_text()), signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        if parent.poll() is None:
                            parent.kill()
                        parent.communicate(timeout=3)

    def test_launch_uses_waypipe_and_exact_id(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(backend.main(["launch", "node", "odd ' name.desktop"]), 7)
        self.assertEqual(run.call_args.args[0], ["waypipe", "--no-gpu", "--xwls",
                         *backend.ssh_command("node", "run", "odd ' name.desktop")])

    def test_start_detaches_with_private_log_and_inherited_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            desktop_id = "odd '$(no execution).desktop"
            with patch.dict(os.environ, XDG_STATE_HOME=tmp, WAYLAND_DISPLAY="wayland-test",
                            SSH_AUTH_SOCK="/agent", XDG_RUNTIME_DIR="/runtime"):
                def spawn(argv, **kwargs):
                    self.assertEqual(argv, [sys.executable, str(Path(backend.__file__).resolve()),
                                           "launch", "node", desktop_id, "--failure-log", argv[-1]])
                    self.assertTrue(kwargs["start_new_session"])
                    self.assertTrue(kwargs["close_fds"])
                    self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                    self.assertIs(kwargs["stdout"], kwargs["stderr"])
                    self.assertEqual(os.fstat(kwargs["stdout"].fileno()).st_mode & 0o777, 0o600)
                    self.assertEqual(kwargs["umask"], 0o077)
                    self.assertEqual(kwargs["cwd"], "/")
                    self.assertEqual(kwargs["env"], dict(os.environ))
                    self.assertFalse(kwargs.get("shell", False))
                with patch.object(subprocess, "Popen", side_effect=spawn) as popen:
                    self.assertEqual(backend.main(["start", "node", desktop_id]), 0)
                    self.assertTrue(popen.call_args.kwargs["stdout"].closed)
            logs = list((Path(tmp) / "quickshell/remote-apps").glob("*.log"))
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0].parent.stat().st_mode & 0o777, 0o700)

    def test_start_spawn_failure_returns_stderr_and_closes_log(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, XDG_STATE_HOME=tmp):
            with patch.object(subprocess, "Popen", side_effect=FileNotFoundError("missing helper")) as popen:
                with contextlib.redirect_stderr(io.StringIO()) as errors:
                    self.assertEqual(backend.main(["start", "node", "app.desktop"]), 1)
                self.assertIn("missing helper", errors.getvalue())
                self.assertTrue(popen.call_args.kwargs["stdout"].closed)

    def test_detached_worker_outlives_parent_without_holding_pipes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            helper = root / "waypipe"
            helper.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys, time\n"
                "from pathlib import Path\n"
                "print(json.dumps({'sid': os.getsid(0), 'pid': os.getpid(), "
                "'display': os.environ['WAYLAND_DISPLAY'], 'stdin': sys.stdin.read()}), flush=True)\n"
                "print('stderr redirected', file=sys.stderr, flush=True)\n"
                "deadline = time.monotonic() + 5\n"
                "while not Path(os.environ['RELEASE']).exists() and time.monotonic() < deadline:\n"
                "    time.sleep(0.01)\n"
                "print('finished', flush=True)\n"
            )
            helper.chmod(0o700)
            env = dict(os.environ, PATH=tmp, XDG_STATE_HOME=tmp,
                       WAYLAND_DISPLAY="wayland-test", RELEASE=str(root / "release"))
            try:
                parent = subprocess.run(
                    [sys.executable, "-B", backend.__file__, "start", "node", "app.desktop"],
                    env=env, capture_output=True, text=True, timeout=3,
                )
                self.assertEqual((parent.returncode, parent.stdout, parent.stderr), (0, "", ""))
                log = next((root / "quickshell/remote-apps").glob("*.log"))
                deadline = time.monotonic() + 3
                while "stderr redirected" not in log.read_text() and time.monotonic() < deadline:
                    time.sleep(0.01)
                content = log.read_text()
                metadata = json.loads(content.splitlines()[0])
                self.assertNotEqual(metadata["sid"], os.getsid(0))
                self.assertNotEqual(metadata["sid"], metadata["pid"])
                self.assertEqual(metadata["display"], "wayland-test")
                self.assertEqual(metadata["stdin"], "")
                self.assertIn("stderr redirected", content)
                self.assertNotIn("finished", content)
            finally:
                (root / "release").touch()
            deadline = time.monotonic() + 3
            while "finished" not in log.read_text() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIn("finished", log.read_text())

    def test_supervisor_reports_remote_failure_as_single_ipc_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "private.log"
            log.write_text("x" * 5000 + "\nquickshell-remote-apps: command not found; $(data)\n")
            with patch.object(subprocess, "run", side_effect=[
                subprocess.CompletedProcess([], 127), subprocess.CompletedProcess([], 0),
            ]) as run:
                self.assertEqual(backend.main(["launch", "node", "app.desktop", "--failure-log", str(log)]), 127)
            call = run.call_args
            self.assertEqual(call.args[0][:5], ["qs", "ipc", "call", "launcher", "failure"])
            self.assertEqual(len(call.args[0]), 6)
            self.assertIn("app.desktop on node failed", call.args[0][-1])
            self.assertIn("command not found; $(data)", call.args[0][-1])
            self.assertIn(str(log), call.args[0][-1])
            self.assertLess(len(call.args[0][-1]), 600)
            self.assertEqual(call.kwargs, {"stdin": subprocess.DEVNULL, "check": True, "timeout": 5})

    def test_supervisor_local_start_failure_and_unavailable_ipc(self):
        with patch.object(subprocess, "run", side_effect=[
            FileNotFoundError("waypipe missing"), subprocess.TimeoutExpired("qs", 5),
        ]) as run, contextlib.redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(backend.launch_app("node", "app.desktop", "/missing/log"), 1)
        self.assertEqual(run.call_count, 2)
        self.assertIn("waypipe missing", errors.getvalue())
        self.assertIn("failure notification unavailable", errors.getvalue())

    def test_successful_supervisor_does_not_notify(self):
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.assertEqual(backend.launch_app("node", "app.desktop", "/unused/log"), 0)
            self.assertEqual(run.call_count, 1)


try:
    Gio, GLib = backend.gi_modules()
except (ImportError, ValueError):
    Gio = GLib = None


@unittest.skipIf(Gio is None, "Python GObject unavailable")
class GioTests(unittest.TestCase):
    def test_headless_themed_icon_lookup(self):
        with patch.dict(os.environ, DISPLAY="", WAYLAND_DISPLAY=""):
            theme = backend.icon_theme()
            self.assertIsNotNone(theme)
            info = theme.lookup_icon("application-x-executable", 64, 0)
            self.assertIsNotNone(info)
            self.assertIsNotNone(backend.icon_data(info.get_filename()))

    def test_metadata_filtering_no_exec_and_direct_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user, system = root / "user", root / "system"
            marker = root / "executed"
            for directory in (user, system):
                (directory / "applications").mkdir(parents=True)
            base = '[Desktop Entry]\nType=Application\nName=Test\nExec=/bin/sh -c "touch %s"\n' % marker
            for name, suffix in (("hidden", "Hidden=true\n"), ("nodisplay", "NoDisplay=true\n"),
                                 ("missing", "TryExec=/no/such/program\n")):
                (user / f"applications/{name}.desktop").write_text(base + suffix)
                (system / f"applications/{name}.desktop").write_text(base)
            entry = user / "applications/visible.desktop"
            entry.write_text(base + "DBusActivatable=true\nIcon=application-x-executable\n")
            with patch.dict(os.environ, XDG_DATA_HOME=str(user), XDG_DATA_DIRS=str(system)):
                apps = backend.export_apps()
                self.assertEqual([item["id"] for item in apps], ["visible.desktop"])
                self.assertFalse(marker.exists())
                self.assertFalse(backend.direct_app(Gio, GLib, entry).get_boolean("DBusActivatable"))
                self.assertEqual(backend.run_app("visible.desktop"), 0)
                self.assertTrue(marker.exists())

    def test_percent_k_preserves_original_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            entry = Path(tmp) / 'odd " $ name.desktop'
            entry.write_text('[Desktop Entry]\nType=Application\nName=Test\nExec=/bin/sh %%k %k\n')
            app = backend.direct_app(Gio, GLib, entry)
            self.assertIn("%%k", app.get_commandline())
            self.assertIn(str(entry).replace('"', '\\"').replace('$', '\\$'), app.get_commandline())


if __name__ == "__main__":
    unittest.main()
