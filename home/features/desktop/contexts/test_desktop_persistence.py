"""Opt-in real desktop acceptance; run with PERSISTENCE_DESKTOP_TESTS=1.

No model requests, authentication, reboot, notes launch, or user-server discovery.
Only socket discovery is narrowed: all coordinator/adapters/compositor calls are
real. Failed runs retain isolated artifacts under /tmp/opencode for diagnosis.
"""

import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import unittest
import uuid

import contextctl as ctl
import persistence as p
import chat_portability as chats


DIRECTORY = Path(__file__).resolve().parent
TMUX = os.environ.get("PERSISTENCE_TMUX") or shutil.which("tmux") or "tmux"
RESURRECT = os.environ.get("PERSISTENCE_RESURRECT", "")
ADAPTER = DIRECTORY.parents[1] / "development/nvim/config/lua/context_persistence.lua"
PLUGIN = DIRECTORY.parents[1] / "agents/opencode/tui-plugins/context-persistence.js"


@unittest.skipUnless(os.environ.get("PERSISTENCE_DESKTOP_TESTS") == "1",
                     "set PERSISTENCE_DESKTOP_TESTS=1 for disposable desktop acceptance")
class DesktopPersistenceTests(unittest.TestCase):
    maxDiff = None

    def wait(self, description, function, timeout=20):
        deadline, last = time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            try:
                value = function()
                if value:
                    return value
                last = repr(value)
            except (OSError, ValueError, ctl.ContextError, subprocess.SubprocessError) as exc:
                last = str(exc)
            time.sleep(.1)
        self.fail(f"{description}: {last}; artifacts: {self.base}")

    def setUp(self):
        self.original_env = dict(os.environ)
        self.addCleanup(self.restore_environment)
        for binary in (TMUX, "hyprctl", "kitty", "nvim", "opencode", "loginctl"):
            self.assertTrue(shutil.which(binary), f"BLOCKER: executable unavailable: {binary}")
        if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            instances = json.loads(p.run(["hyprctl", "instances", "-j"]))
            matches = [i for i in instances if i.get("wl_socket") == os.environ.get("WAYLAND_DISPLAY")]
            self.assertEqual(len(matches), 1, "BLOCKER: cannot identify graphical compositor unambiguously")
            os.environ["HYPRLAND_INSTANCE_SIGNATURE"] = matches[0]["instance"]
        self.assertTrue(os.environ.get("XDG_RUNTIME_DIR"), "BLOCKER: XDG_RUNTIME_DIR absent")
        self.assertTrue(os.environ.get("WAYLAND_DISPLAY"), "BLOCKER: WAYLAND_DISPLAY absent")
        self.monitors = json.loads(p.run(["hyprctl", "-j", "monitors"]))
        self.assertTrue(self.monitors, "BLOCKER: compositor has no graphical outputs")
        self.prior_active = ctl.snapshot()["active"]
        self.prior_focus = json.loads(p.run(["hyprctl", "-j", "activewindow"])).get("address")
        self.prior_clients = {w["address"] for w in ctl.clients()}
        self.base = Path(tempfile.mkdtemp(prefix="desktop-persistence-", dir="/tmp/opencode"))
        self.runtimes, self.runtime_names, self.classes, self.processes = set(), set(), set(), []
        self.servers = [p.Tmux(self.base / "source.sock"), p.Tmux(self.base / "destination.sock")]
        self.tm, self.destination = self.servers
        self.discovery = p.sockets
        # Safety scope, not simulated inventory: never even query user tmux servers.
        p.sockets = self.owned_sockets
        self.addCleanup(self.cleanup_desktop)
        self.addCleanup(self.diagnostics)
        runtime = self.base / "runtime"
        runtime.mkdir(mode=0o700)
        actual_runtime = Path(os.environ["XDG_RUNTIME_DIR"])
        self.compositor_runtime = str(actual_runtime)
        for name in ("hypr", os.environ["WAYLAND_DISPLAY"],
                     f"hyprland-sessions-{ctl.signature()}.json"):
            (runtime / name).symlink_to(actual_runtime / name)
        for name in tuple(os.environ):
            if name.startswith(("OPENCODE_", "CONTEXT_EDITOR_")) or name in (
                    "TMUX", "TMUX_PANE", "CONTEXT_DIRECTORY"):
                os.environ.pop(name, None)
        for key, leaf in (("HOME", "home"), ("XDG_STATE_HOME", "state"),
                          ("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                          ("XDG_CACHE_HOME", "cache")):
            path = self.base / leaf
            path.mkdir()
            os.environ[key] = str(path)
        os.environ.update(
            XDG_RUNTIME_DIR=str(runtime), CONTEXT_ROOT=str(self.base / "contexts"),
            PERSISTENCE_TMUX=TMUX, PERSISTENCE_RESURRECT=RESURRECT,
            OPENCODE_DB=str(self.base / "opencode.db"),
            OPENCODE_DISABLE_PROJECT_CONFIG="1", OPENCODE_DISABLE_DEFAULT_PLUGINS="1",
            OPENCODE_CONFIG_CONTENT='{"plugin":[],"provider":{}}',
            OPENCODE_DISABLE_MODELS_FETCH="1", OPENCODE_DISABLE_AUTOUPDATE="1",
            SHELL="/bin/sh", TERM="xterm-256color",
            PERSISTENCE_DESKTOP_OWNER=str(self.base),
        )
        self.assertTrue((Path(RESURRECT) / "scripts/save.sh").is_file())
        self.assertTrue(ADAPTER.is_file())
        self.assertTrue(PLUGIN.is_file())
        config = Path(os.environ["XDG_CONFIG_HOME"]) / "opencode"
        config.mkdir()
        ctl.atomic_json(config / "tui.json", {"plugin": [str(PLUGIN)]})
        kitty_config = Path(os.environ["XDG_CONFIG_HOME"]) / "kitty"
        kitty_config.mkdir()
        (kitty_config / "kitty.conf").write_text("confirm_os_window_close 0\n")
        self.make_wrappers()
        self.context = ctl.find_context(ctl.create("Desktop acceptance " + self.base.name)["id"])
        ctl.evaluate("require('context-terminals').setup()")
        self.runtime = self.create_runtime()
        # Harmless logind query only. No power/session mutation.
        p.run(["loginctl", "list-sessions", "--no-legend"])

    def restore_environment(self):
        os.environ.clear()
        os.environ.update(self.original_env)

    def owned_sockets(self, extra=None):
        if extra:
            self.assertIn(str(extra), [tm.socket for tm in self.servers])
        return [tm for tm in self.servers if Path(tm.socket).is_socket()]

    def make_wrappers(self):
        binary = shutil.which("nvim")
        hyprctl = shutil.which("hyprctl")
        directory = self.base / "bin"
        directory.mkdir()
        init = self.base / "editor.lua"
        init.write_text("package.loaded.context_persistence = dofile(" + p.lua_value(str(ADAPTER))
                        + ")\nrequire('context_persistence').setup()\n")
        wrapper = directory / "nvim"
        wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(binary)
                           + " -u NONE -i NONE -n --cmd "
                           + shlex.quote("luafile " + str(init)) + ' "$@"\n')
        wrapper.chmod(0o700)
        (directory / "tmux").symlink_to(TMUX)
        # Hyprland's long instance signature exceeds AF_UNIX's 108-byte limit
        # under our temp root. Only compositor IPC uses its existing runtime;
        # editor/chat sockets and coordinator snapshots remain isolated.
        ipc = directory / "hyprctl"
        ipc.write_text("#!/bin/sh\nexport XDG_RUNTIME_DIR=" + shlex.quote(self.compositor_runtime)
                       + "\nexec " + shlex.quote(hyprctl) + ' "$@"\n')
        ipc.chmod(0o700)
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ["PATH"]

    def create_runtime(self):
        name = self.base.name + "-" + uuid.uuid4().hex[:8]
        self.runtime_names.add(name)
        ctl.evaluate("require('sessions').create(" + ctl.lua_string(name) + ")")
        entry = self.wait("new runtime snapshot", lambda: next(
            (s for s in ctl.snapshot()["sessions"] if s["name"] == name), None))
        runtime = entry["id"]
        self.runtimes.add(runtime)
        ctl.save_state({"mappings": {self.context["id"]: runtime}, "last_active": self.context["id"]})
        self.assertEqual(ctl.launch_context(runtime)["id"], self.context["id"])
        return runtime

    def diagnostics(self):
        # Preserve failures and real CLI logs rather than interpreting restore's
        # bool as success (it also returns True after individual recovery errors).
        for name, function in (("clients", ctl.clients), ("runtime", ctl.snapshot)):
            try:
                ctl.atomic_json(self.base / (name + ".json"), function())
            except Exception as exc:
                (self.base / (name + ".error")).write_text(str(exc))
        for index, tm in enumerate(self.servers):
            if not Path(tm.socket).is_socket():
                continue
            try:
                panes = self.panes(tm)
                ctl.atomic_json(self.base / f"server-{index}-panes.json", panes)
                for pane in panes:
                    (self.base / f"server-{index}-{pane['pane_id']}.screen").write_text(
                        tm.call("capture-pane", "-p", "-S", "-200", "-t", pane["pane_id"]))
            except Exception as exc:
                (self.base / f"server-{index}.error").write_text(str(exc))
        print(f"Desktop acceptance artifacts: {self.base}", flush=True)

    def cleanup_desktop(self):
        errors = []
        try:
            for window in ctl.clients():
                if window.get("class") in self.classes and window["address"] not in self.prior_clients:
                    try:
                        self.dispatch_window("window.close", window["address"])
                    except Exception as exc:
                        errors.append(str(exc))
            for tm in self.servers:
                if Path(tm.socket).is_socket():
                    subprocess.run([TMUX, "-S", tm.socket, "set-option", "-su", "@persistence-checkpoint"],
                                   capture_output=True, timeout=5)
                    subprocess.run([TMUX, "-S", tm.socket, "kill-server"], capture_output=True, timeout=10)
            # Kill only descendants launched by this test, plus marked orphaned
            # TUI workers. Never use pkill, default sockets, or user server PIDs.
            for proc in Path("/proc").iterdir():
                if not proc.name.isdigit() or int(proc.name) == os.getpid():
                    continue
                try:
                    marker = b"PERSISTENCE_DESKTOP_OWNER=" + os.fsencode(self.base) + b"\0"
                    if marker in (proc / "environ").read_bytes():
                        os.kill(int(proc.name), signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
            for process, stream in self.processes:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                stream.close()
            self.wait("test windows closed", lambda: not any(
                w.get("class") in self.classes for w in ctl.clients()), timeout=10)
            self.runtimes.update(s["id"] for s in ctl.snapshot()["sessions"]
                                 if s["name"] in self.runtime_names)
            for runtime in self.runtimes:
                if any(s["id"] == runtime for s in ctl.snapshot()["sessions"]):
                    ctl.evaluate("require('context-terminals').close_checkpointed(" + ctl.lua_string(runtime) + ")")
            self.wait("disposable runtimes removed", lambda: not any(
                s["id"] in self.runtimes for s in ctl.snapshot()["sessions"]), timeout=10)
        finally:
            p.sockets = self.discovery
            if self.prior_active:
                ctl.evaluate("require('sessions').switch(" + ctl.lua_string(self.prior_active) + ")")
            if self.prior_focus and any(w["address"] == self.prior_focus for w in ctl.clients()):
                self.dispatch_window("focus", self.prior_focus)
        self.assertEqual(errors, [], "Disposable desktop cleanup failed")
        self.assertTrue(self.prior_clients <= {w["address"] for w in ctl.clients()},
                        "Preexisting user windows disappeared")

    def rpc(self, socket, lua):
        return p.run(["nvim", "--server", socket, "--remote-expr",
                      "luaeval(" + json.dumps(lua) + ")"])

    def dispatch_window(self, operation, address):
        ctl.evaluate("assert(hl.dispatch(hl.dsp." + operation + "({window="
                     + ctl.lua_string("address:" + address) + "})).ok)")

    def panes(self, tm):
        return tm.rows("list-panes", ["pane_id", "pane_pid", "pane_current_command",
                       "@persistence-id", "@persistence-editor", "@persistence-editor-socket",
                       "@persistence-chat-socket"], "-a")

    def ready_editors(self, tm):
        panes = self.panes(tm)
        editors = [q for q in panes if q["@persistence-editor-socket"]
                   and Path(q["@persistence-editor-socket"]).is_socket()]
        return editors if len(editors) == 2 else None

    def selections(self, tm):
        result = []
        for pane in self.panes(tm):
            socket = pane["@persistence-chat-socket"]
            if socket and Path(socket).is_socket():
                route = chats.read_selection(Path(socket), int(pane["pane_pid"]), tm.socket, pane["pane_id"])
                if route["session_id"]:
                    result.append((pane, route))
        return result if len(result) == 2 else None

    def place(self, address, slot, role=None, floating=False):
        placement = {"address": address, "monitor": self.monitors[0]["name"],
                     "workspace": {"slot": slot, "role": role}, "floating": floating,
                     "geometry": [.15, .18, .42, .48], "fullscreen": 0, "fullscreen_client": 0}
        ctl.evaluate("require('context-terminals').place(" + ctl.lua_string(self.runtime)
                     + "," + p.lua_value(placement) + ")")

    def launch_kitty(self, index):
        cls = "context-terminal-" + str(uuid.uuid4())
        self.classes.add(cls)
        stream = (self.base / f"kitty-{index}.log").open("w")
        process = subprocess.Popen(["kitty", "--override", "confirm_os_window_close=0", "--class", cls,
                                    "--directory", self.context["cwd"], "tmux", "-S", self.tm.socket,
                                    "attach-session", "-t", "acceptance"], stdout=stream, stderr=stream)
        self.processes.append((process, stream))
        return self.wait(f"Kitty {index} maps (see kitty-{index}.log)", lambda: next(
            (w for w in ctl.clients() if w.get("class") == cls), None))

    def assert_recovered(self, desktop, saved):
        retained = ctl.read_json(p.local_root() / f"retained-{self.context['id']}.json")
        self.assertEqual(retained["sessions"], [], "Restore unresolved: inspect terminal/events.log")
        expected = {"context-terminal-" + w["id"]: w for w in desktop["windows"]}
        self.classes.update(expected)
        clients = self.wait("restored Kitty window count", lambda: (
            [w for w in ctl.clients() if w.get("class") in expected]
            if len([w for w in ctl.clients() if w.get("class") in expected]) == 3 else None))
        attachments = self.wait("three native clients attached", lambda: (
            self.destination.rows("list-clients", ["client_pid", "session_id"])
            if len(self.destination.rows("list-clients", ["client_pid", "session_id"])) == 3 else None))
        self.assertEqual(len({c["session_id"] for c in attachments}), 1)
        captured = p.capture_tmux(self.destination, ctl.scan())
        inventory = p.inventory(self.context, [(tm, session) for _, tm, session in captured])
        self.assertEqual(inventory["warnings"], [])
        self.assertEqual({w["id"]: w["session"] for w in inventory["windows"]},
                         {w["id"]: w["session"] for w in desktop["windows"]},
                         "Each real Kitty process must own its expected native tmux client")
        time.sleep(.5)  # Let real compositor animations finish before pixel assertions.
        clients = [w for w in ctl.clients() if w.get("class") in expected]
        for window in clients:
            source = expected[window["class"]]
            logical = source["workspace"]
            name = window["workspace"]["name"]
            if logical["role"]:
                self.assertEqual(name, f"special:session-{self.runtime}-{logical['role']}")
            else:
                self.assertTrue(name.startswith(f"session-{self.runtime}-"), name)
                self.assertTrue(name.endswith("-" + str(logical["slot"])), name)
            self.assertEqual(window["floating"], source["floating"])
            if source["floating"]:
                monitor = next(m for m in self.monitors if m["name"] == source["monitor"])
                width, height = monitor["width"] / monitor["scale"], monitor["height"] / monitor["scale"]
                if monitor["transform"] % 2:
                    width, height = height, width
                actual = [window["at"][0] - monitor["x"], window["at"][1] - monitor["y"], *window["size"]]
                for observed, norm, dimension in zip(actual, source["geometry"], [width, height, width, height]):
                    self.assertAlmostEqual(observed, norm * dimension, delta=4)
        focused = json.loads(p.run(["hyprctl", "-j", "activewindow"]))
        self.assertEqual(focused.get("class"), next(cls for cls, w in expected.items() if w["focused"]))
        editors = self.wait("restored editor adapters", lambda: self.ready_editors(self.destination))
        self.assertEqual({q["@persistence-editor"] for q in editors},
                         {q["editor"]["id"] for w in saved[0]["windows"] for q in w["panes"] if "editor" in q})
        for editor in editors:
            buffers = json.loads(self.rpc(editor["@persistence-editor-socket"],
                "vim.json.encode((function() local r={} for _,b in ipairs(vim.api.nvim_list_bufs()) do "
                "if vim.b[b].context_recovery then r[#r+1]={original=vim.b[b].context_original_file,"
                "lines=vim.api.nvim_buf_get_lines(b,0,-1,false),modified=vim.bo[b].modified} end end return r end)())"))
            self.assertEqual(len(buffers), 2)
            self.assertTrue(all(b["modified"] for b in buffers))
            suffix = self.editor_suffix[editor["@persistence-editor"]]
            self.assertEqual({tuple(b["lines"]) for b in buffers},
                             {("modified-" + suffix,), ("unnamed-" + suffix,)})
            self.assertEqual({b["original"] for b in buffers},
                             {str(Path(self.context["cwd"]) / "original.txt"), "[unnamed]"})
        routes = self.wait("actual restored TUI routes", lambda: self.selections(self.destination), timeout=60)
        self.assertEqual({r["session_id"] for _, r in routes}, self.chat_ids)
        for _, route in routes:
            self.assertEqual(chats._export(route["session_id"], self.context["cwd"])["messages"], [])
        for output in desktop["desktop"]:
            monitor = next(m for m in json.loads(p.run(["hyprctl", "-j", "monitors"]))
                           if m["name"] == output["monitor"])
            self.assertTrue(monitor["activeWorkspace"]["name"].endswith("-" + str(output["slot"])))
            expected_special = (f"special:session-{self.runtime}-{output['role']}" if output["role"] else "")
            self.assertEqual(monitor["specialWorkspace"]["name"], expected_special)
        return sorted((w["address"], w["pid"]) for w in clients)

    def test_real_checkpoint_close_reconstruct_and_live_reopen(self):
        cwd = self.context["cwd"]
        original = Path(cwd) / "original.txt"
        original.write_text("original on disk\n")
        self.chat_ids = {"ses_desktop" + uuid.uuid4().hex for _ in range(2)}
        for index, sid in enumerate(sorted(self.chat_ids)):
            fixture = {"info": {"id": sid, "slug": "desktop-acceptance-" + str(index),
                "projectID": "global", "directory": cwd, "title": "Desktop empty chat " + str(index),
                "version": "1.19.3", "time": {"created": int(time.time() * 1000),
                "updated": int(time.time() * 1000)}}, "messages": []}
            path = self.base / f"chat-{index}.json"
            ctl.atomic_json(path, fixture)
            chats._cli(["import", str(path)], cwd)
            self.assertEqual(chats._export(sid, cwd)["messages"], [])
        p.run([TMUX, "-S", self.tm.socket, "-f", "/dev/null", "new-session", "-d", "-x", "180", "-y", "55",
               "-s", "acceptance", "-c", cwd, "nvim"])
        self.tm.call("set-option", "-g", "default-shell", "/bin/sh")
        self.tm.call("set-option", "-t", "acceptance", "@persistence-context", self.context["id"])
        self.tm.call("new-window", "-d", "-t", "acceptance:1", "-c", cwd, "nvim")
        for index, sid in enumerate(sorted(self.chat_ids), 2):
            self.tm.call("new-window", "-d", "-t", f"acceptance:{index}", "-c", cwd,
                         "opencode", "--session", sid)
        editors = self.wait("two real Neovim adapters", lambda: self.ready_editors(self.tm))
        self.assertEqual(len({q["@persistence-editor"] for q in editors}), 2)
        self.editor_suffix = {q["@persistence-editor"]: str(i) for i, q in enumerate(editors, 1)}
        for index, editor in enumerate(editors, 1):
            self.rpc(editor["@persistence-editor-socket"],
                     "(function() vim.cmd('edit original.txt'); "
                     f"vim.api.nvim_buf_set_lines(0,0,-1,false,{{'modified-{index}'}}); "
                     "vim.cmd('vnew'); "
                     f"vim.api.nvim_buf_set_lines(0,0,-1,false,{{'unnamed-{index}'}}); return 'ok' end)()")
        # Select both chat windows once to force real terminal rendering, not a
        # headless API/plugin harness. No keystrokes submit any prompt.
        windows = [self.launch_kitty(index) for index in range(3)]
        for index in (2, 3):
            self.tm.call("select-window", "-t", f"acceptance:{index}")
            time.sleep(1)
        routes = self.wait("two rendered native TUI plugin routes (inspect pane/log artifacts on failure)",
                           lambda: self.selections(self.tm), timeout=60)
        self.assertEqual({r["session_id"] for _, r in routes}, self.chat_ids)
        for pane, route in routes:
            screen = self.tm.call("capture-pane", "-p", "-t", pane["pane_id"])
            (self.base / (pane["pane_id"].replace("%", "pane-") + ".screen")).write_text(screen)
            self.assertTrue(screen.strip(), "OpenCode TUI rendered no terminal content")
            self.assertIn(route["session_id"], self.chat_ids)
        self.tm.call("select-window", "-t", "acceptance:0")
        self.place(windows[0]["address"], 2)
        self.place(windows[1]["address"], 4, floating=True)
        self.place(windows[2]["address"], 2, role="terminal", floating=True)
        ctl.evaluate("require('context-terminals').view(" + ctl.lua_string(self.runtime) + ","
                     + p.lua_value([{"monitor": self.monitors[0]["name"], "slot": 2, "role": "terminal"}]) + ")")
        self.dispatch_window("focus", windows[2]["address"])
        time.sleep(.5)
        p.checkpoint("close", self.context["id"], self.tm.socket)
        base, manifest = p.latest(self.context)
        p.validate(base, manifest)
        self.assertEqual(manifest["warnings"], [], "Fixture checkpoint must be complete")
        desktop, saved = ctl.read_json(base / "desktop.json"), ctl.read_json(base / "tmux.json")
        self.assertEqual(len(desktop["windows"]), 3)
        self.assertEqual({w["workspace"]["slot"] for w in desktop["windows"] if not w["workspace"]["role"]}, {2, 4})
        self.assertEqual([w["workspace"]["role"] for w in desktop["windows"] if w["workspace"]["role"]], ["terminal"])
        self.assertEqual(sum(w["floating"] for w in desktop["windows"]), 2)
        self.assertEqual(len({w["session"] for w in desktop["windows"]}), 1)
        self.assertEqual(len(saved), 1)
        self.assertEqual(sum(len(w["panes"]) for w in saved[0]["windows"]), 4)
        self.assertEqual(sum(w["focused"] for w in desktop["windows"]), 1)
        p.set_lifecycle(self.context, "closed")
        closed = self.runtime
        ctl.evaluate("require('context-terminals').close_checkpointed(" + ctl.lua_string(closed) + ")")
        self.wait("checkpointed runtime closes", lambda: not any(
            s["id"] == closed for s in ctl.snapshot()["sessions"]))
        self.assertFalse(any(w.get("class") in self.classes for w in ctl.clients()))
        # Completed save precedes bypassed destruction of this isolated server.
        self.tm.call("set-option", "-su", "@persistence-checkpoint")
        self.tm.call("kill-server")
        self.runtime = self.create_runtime()
        p.set_lifecycle(self.context, "open")
        self.classes.update("context-terminal-" + w["id"] for w in desktop["windows"])
        self.assertTrue(p.restore(self.context, self.runtime, tm=self.destination))
        before = self.assert_recovered(desktop, saved)
        panes_before = self.destination.call("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}")
        ctl.open_context(self.context["id"])  # Existing runtime: no notes launch.
        self.assertTrue(p.restore(self.context, self.runtime, tm=self.destination))
        self.assertEqual(self.assert_recovered(desktop, saved), before)
        self.assertEqual(self.destination.call("list-panes", "-a", "-F", "#{pane_id} #{pane_pid}"), panes_before)
        self.assertEqual(original.read_text(), "original on disk\n")
        events = (p.local_root() / "events.log").read_text()
        allowed = ("Published ", "Tiled terminal order/size approximated:")
        self.assertEqual([line for line in events.splitlines() if not any(s in line for s in allowed)], [],
                         "Coordinator reported recovery errors; bool return alone is insufficient")


if __name__ == "__main__":
    unittest.main()
