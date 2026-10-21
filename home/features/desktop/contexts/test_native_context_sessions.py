"""Opt-in HTTP acceptance against the installed, patched OpenCode; fixture DB only."""
import json
import os
import pty
import select
import socket
import subprocess
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

import context_chat_library as library
import contextctl as ctl
import organization
from test_chat_portability import PLUGIN
from test_context_chat_library import ScopeTests


@unittest.skipUnless(os.environ.get("PERSISTENCE_NATIVE_TESTS") == "1", "set PERSISTENCE_NATIVE_TESTS=1")
class NativeScopeTests(ScopeTests):
    def server(self, context=None):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = dict(os.environ, OPENCODE_CONTEXT_HELPER="1")
        env.pop("CONTEXT_ID", None)
        env.pop("OPENCODE_CONTEXT_SCOPE_FILE", None)
        if context:
            context = ctl.find_context(context["id"])
            library.publish_scopes(ctl.scan(), library.database_path())
            env.update(CONTEXT_ID=context["id"], CONTEXT_DIRECTORY=context["path"],
                       OPENCODE_CONTEXT_SCOPE_FILE=str(library.scope_path(context, library.database_path())))
        log = (self.base / f"server-{port}.log").open("w+")
        process = subprocess.Popen(["opencode", "serve", "--port", str(port), "--hostname", "127.0.0.1"],
                                   cwd=self.work, env=env, stdout=log, stderr=log)

        def cleanup():
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            log.close()
        self.addCleanup(cleanup)
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                log.seek(0)
                self.fail("OpenCode server failed: " + log.read())
            try:
                with urlopen(base + "/global/health", timeout=1):
                    break
            except OSError:
                time.sleep(.1)
        else:
            self.fail("OpenCode server did not become ready")

        def request(path, data=None, method=None):
            req = Request(base + path, data=json.dumps(data).encode() if data is not None else None,
                          method=method, headers={"Content-Type": "application/json", "x-opencode-directory": str(self.work)})
            with urlopen(req, timeout=30) as response:
                return json.load(response)
        return request

    def test_native_ownership_lists_search_limits_and_live_hierarchy(self):
        parent = self.server(self.parent)
        child = self.server(self.child)
        sibling = self.server(self.sibling)
        focused = child("/session", {"title": "focused-child"})
        marker = focused["metadata"]["desktop_context"]
        self.assertEqual(marker, {"id": self.child["id"], "chat": focused["id"], "session": focused["id"]})
        for number in range(5):
            sibling("/session", {"title": "focused-sibling-" + str(number)})
        broad = parent("/session", {"title": "parent-work"})
        subagent = parent("/session", {"parentID": focused["id"], "title": "subagent"})
        self.assertEqual(subagent["metadata"]["desktop_context"]["id"], self.child["id"])
        self.assertEqual(subagent["metadata"]["desktop_context"]["chat"], focused["id"])
        # Metadata changes through the parent may add fields but never transfer ownership.
        updated = parent("/session/" + focused["id"], {"title": "focused-child-edited", "metadata": {
            "unrelated": "preserve", "desktop_context": {"id": self.parent["id"]}}}, "PATCH")
        self.assertEqual(updated["metadata"]["desktop_context"], marker)
        self.assertEqual(updated["metadata"]["unrelated"], "preserve")
        roots = child("/session?roots=true&limit=100")
        self.assertEqual([row["id"] for row in roots], [focused["id"]])
        self.assertEqual([row["id"] for row in child("/session?roots=true&search=focused&limit=1")], [focused["id"]])
        self.assertEqual(len(parent("/session?roots=true&limit=100")), 7)
        self.assertEqual([row["id"] for row in child("/experimental/session?roots=true&limit=100")], [focused["id"]])
        fork = parent("/session/" + focused["id"] + "/fork", {})
        self.assertEqual(fork["metadata"]["desktop_context"], {
            "id": self.child["id"], "chat": fork["id"], "session": fork["id"]})
        organization.change([self.child["id"]], parent=None)
        library.refresh_scopes(ctl.scan())
        self.assertNotIn(focused["id"], {row["id"] for row in parent("/session?roots=true&limit=100")})
        self.assertIn(broad["id"], {row["id"] for row in parent("/session?roots=true&limit=100")})

    def test_unowned_history_is_not_guessed_and_direct_launch_stays_global(self):
        global_view = self.server()
        legacy = global_view("/session", {"title": "unowned-existing"})
        self.assertNotIn("desktop_context", legacy.get("metadata", {}))
        scoped = self.server(self.child)
        owned = scoped("/session", {"title": "owned-new"})
        self.assertEqual([row["id"] for row in scoped("/session?roots=true")], [owned["id"]])
        self.assertEqual({row["id"] for row in global_view("/session?roots=true")}, {legacy["id"], owned["id"]})
        self.assertEqual([row["id"] for row in library.unowned(ctl.find_context(self.child["id"]))], [legacy["id"]])
        scoped("/session/" + legacy["id"], {"metadata": {"desktop_context": {
            "id": self.child["id"], "chat": legacy["id"], "session": legacy["id"]}}}, "PATCH")
        self.assertEqual({row["id"] for row in scoped("/session?roots=true")}, {legacy["id"], owned["id"]})
        self.assertEqual(library.unowned(ctl.find_context(self.child["id"])), [])

    def test_native_tui_loads_context_library_plugin(self):
        child = self.server(self.child)
        owned = child("/session", {"title": "TUI plugin smoke"})
        config = Path(os.environ["XDG_CONFIG_HOME"]) / "opencode"
        config.mkdir(parents=True, exist_ok=True)
        probe = self.base / "probe.js"
        result = self.base / "plugin-ready.json"
        probe.write_text('import {writeFileSync} from "node:fs"; export default {id:"context-library-probe",tui:async(api)=>{'
                         'const timer=setInterval(()=>{const plugin=api.plugins.list().find(x=>x.id==="context-library");'
                         'if(plugin?.active){writeFileSync(' + json.dumps(str(result)) + ',JSON.stringify(plugin));clearInterval(timer)}},50);'
                         'api.lifecycle.onDispose(()=>clearInterval(timer));}}')
        (config / "tui.json").write_text(json.dumps({"plugin": [str(PLUGIN), str(PLUGIN.parent / "context-library.tsx"), str(probe)]}))
        runtime = self.base / "runtime"
        runtime.mkdir()
        env = dict(os.environ, OPENCODE_CONTEXT_HELPER="1", CONTEXT_ID=self.child["id"],
                   CONTEXT_DIRECTORY=ctl.find_context(self.child["id"])["path"],
                   OPENCODE_CONTEXT_SCOPE_FILE=str(library.scope_path(ctl.find_context(self.child["id"]), library.database_path())),
                   XDG_RUNTIME_DIR=str(runtime), TERM="xterm-256color")
        for name in ("OPENCODE_PURE", "TMUX", "TMUX_PANE"):
            env.pop(name, None)
        master, slave = pty.openpty()
        process = subprocess.Popen(["opencode", "--session", owned["id"]], cwd=self.work, env=env,
                                   stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        output = bytearray()
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and process.poll() is None and not result.exists():
                if select.select([master], [], [], .1)[0]:
                    try:
                        output.extend(os.read(master, 65536))
                    except OSError:
                        break
            self.assertTrue(result.exists(), output.decode(errors="replace")[-6000:])
            self.assertTrue(json.loads(result.read_text())["active"])
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            os.close(master)
