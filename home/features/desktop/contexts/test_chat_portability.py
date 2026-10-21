"""Isolated portability regression tests; no persistent user database is used.

Ordinary discovery runs the mocked TUI/real tmux socket test when available.
Native imports/exports require PERSISTENCE_NATIVE_TESTS=1 and opencode on PATH:
    PERSISTENCE_NATIVE_TESTS=1 python test_chat_portability.py -v
"""

import copy
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch


DIRECTORY = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("chat_portability_under_test", DIRECTORY / "chat_portability.py")
chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat)
PLUGIN = DIRECTORY.parents[1] / "agents/opencode/tui-plugins/context-persistence.js"


def native_fixture(root):
    """Native export shape, including all artifact and cross-session references."""
    sid = "ses_wsd1193parent"
    created = 1792270000000

    def message(number, role, parts, **extra):
        mid = f"msg_wsd{number:02}"
        info = {"id": mid, "sessionID": sid, "role": role,
                "time": {"created": created + (number - 1) * 100}, "agent": "build"}
        if role == "user":
            info["model"] = {"providerID": "test-provider", "modelID": "test-model"}
        else:
            info.update(providerID="test-provider", modelID="test-model", mode="build",
                        path={"cwd": str(root), "root": str(root.parent)}, cost=0,
                        tokens={"input": 100, "output": 20, "reasoning": 5,
                                "cache": {"read": 2, "write": 3}}, finish="stop")
            info["time"]["completed"] = info["time"]["created"] + 50
        info.update(extra)
        for part in parts:
            part.update(sessionID=sid, messageID=mid)
        return {"info": info, "parts": parts}

    def part(number, kind, **extra):
        return {"id": f"prt_wsd{number:02}", "type": kind, **extra}

    def completed(output, metadata, **extra):
        return {"status": "completed", "input": {"command": "printf portable"},
                "output": output, "title": "probe", "metadata": metadata,
                "time": {"start": created + 101, "end": created + 199}, **extra}

    attachment = part(10, "file", sessionID=sid, messageID="msg_wsd02", mime="image/png",
                      filename="tool.png", url="data:image/png;base64,aW1hZ2UtYnl0ZXM=")
    return {
        "info": {"id": sid, "slug": "native-probe", "projectID": "source-project",
                 "directory": str(root), "title": "Native portability probe", "version": "1.19.3",
                 "time": {"created": created, "updated": created + 1000},
                 "summary": {"additions": 1, "deletions": 0, "files": 1}},
        "messages": [
            message(1, "user", [
                part(1, "text", text="Inspect attachment, run tool, delegate, then summarize."),
                part(2, "file", mime="text/plain", filename="inline.txt",
                     url="data:text/plain;base64,cG9ydGFibGUtYnl0ZXM="),
                part(3, "file", mime="text/plain", filename="external.txt",
                     url=(root / "external.txt").as_uri(),
                     source={"type": "file", "path": str(root / "external.txt"),
                             "text": {"value": "@external.txt", "start": 0, "end": 13}}),
            ]),
            message(2, "assistant", [
                part(4, "reasoning", text="Check tool result.", time={"start": created + 100, "end": created + 101}),
                part(5, "tool", callID="call_probe", tool="bash",
                     state=completed("portable", {"truncated": True, "outputPath": str(root / "result.txt")},
                                     attachments=[attachment])),
                part(6, "tool", callID="call_task", tool="task",
                     state=completed("Child done", {"sessionId": "ses_wsd1193child"},
                                     input={"prompt": "Investigate child", "subagent_type": "explore"})),
                part(7, "step-finish", reason="tool-calls", snapshot="git-object-not-bundled", cost=0,
                     tokens={"input": 100, "output": 20, "reasoning": 5, "cache": {"read": 2, "write": 3}}),
            ], parentID="msg_wsd01", finish="tool-calls"),
            message(3, "user", [part(8, "compaction", auto=True, overflow=True, tail_start_id="msg_wsd01")]),
            message(4, "assistant", [part(9, "text", text="Compacted: attachment examined; tool and child completed.")],
                    parentID="msg_wsd03", mode="compaction", agent="compaction", summary=True),
        ],
    }


class IsolatedChatTest(unittest.TestCase):
    def setUp(self):
        parent = Path("/tmp/opencode")
        temporary = tempfile.TemporaryDirectory(
            prefix="chat-portability-", dir=parent if parent.is_dir() else None
        )
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.environment_patch = patch.dict(os.environ)
        self.environment_patch.start()
        self.addCleanup(self.environment_patch.stop)
        # Inherited overrides must never direct a native test at a real database
        # or load the user's plugins/configuration.
        for name in tuple(os.environ):
            if name.startswith("OPENCODE_"):
                del os.environ[name]
        self.environment("source")

    def environment(self, name):
        home = self.base / name
        home.mkdir(exist_ok=True)
        os.environ.update(
            HOME=str(home), XDG_CONFIG_HOME=str(home / "config"), XDG_DATA_HOME=str(home / "data"),
            XDG_STATE_HOME=str(home / "state"), XDG_CACHE_HOME=str(home / "cache"),
            OPENCODE_DISABLE_PROJECT_CONFIG="1", OPENCODE_DISABLE_DEFAULT_PLUGINS="1",
            OPENCODE_CONFIG_CONTENT='{"plugin":[]}', OPENCODE_PURE="1",
            OPENCODE_DB=str(home / "opencode.db"),
        )
        return home


@unittest.skipUnless(os.environ.get("PERSISTENCE_NATIVE_TESTS") == "1", "set PERSISTENCE_NATIVE_TESTS=1")
@unittest.skipUnless(shutil.which("opencode"), "opencode unavailable")
class NativeChatPortabilityTests(IsolatedChatTest):
    def test_historical_missing_files_keep_messages_and_report_loss(self):
        root = Path(os.environ["HOME"]) / "context"
        root.mkdir()
        fixture = native_fixture(root)
        seed = self.base / "missing-files-seed.json"
        chat._write(seed, fixture)
        chat._cli(["import", str(seed)], str(root))
        bundle = self.base / "missing-files-bundle"
        manifest = chat.capture({"session_id": fixture["info"]["id"], "directory": str(root)}, bundle, str(root))
        missing = [entry for entry in manifest["unsupported"] if entry.get("reason", "").startswith("Referenced file is missing")]
        self.assertEqual({entry["path"] for entry in missing}, {str(root / "external.txt"), str(root / "result.txt")})
        exported = json.loads((bundle / manifest["sessions"][0]["file"]).read_text())
        self.assertEqual(len(exported["messages"]), len(fixture["messages"]))
        parts = [json.loads((bundle / name).read_text()) for message in exported["messages"] for name in message["parts"]]
        external = next(part for part in parts if part["id"] == "prt_wsd03")
        self.assertEqual(external["url"], (root / "external.txt").as_uri())
        self.assertEqual(external["source"]["path"], str(root / "external.txt"))
        self.assertTrue(any(reference.get("inline") for entry in manifest["sessions"] for reference in entry["references"]))

    def test_large_native_export_is_complete(self):
        root = Path(os.environ["HOME"]) / "context"
        root.mkdir()
        fixture = native_fixture(root)
        text = "Large export: 日本語 🌲\n" * 20000
        fixture["messages"][0]["parts"][0]["text"] = text
        seed = self.base / "large-seed.json"
        chat._write(seed, fixture)
        chat._cli(["import", str(seed)], str(root))

        exported = chat._export(fixture["info"]["id"], str(root))
        self.assertEqual(exported["messages"][0]["parts"][0]["text"], text)
        self.assertEqual(len(exported["messages"]), len(fixture["messages"]))

    def test_changed_message_reuses_other_parts_and_attachments(self):
        import checkpoint_store as store
        from test_checkpoint_store import stats

        root = Path(os.environ["HOME"]) / "context"
        root.mkdir()
        (root / "external.txt").write_text("external attachment")
        (root / "result.txt").write_text("large tool output")
        fixture = native_fixture(root)
        seed = self.base / "seed.json"
        chat._write(seed, fixture)
        chat._cli(["import", str(seed)], str(root))
        tree = store.Tree()
        selection = {"session_id": fixture["info"]["id"], "directory": str(root)}
        chat.capture(selection, tree.path(), str(root))
        storage = store.Store(self.base / "checkpoint", self.base / "checkpoint-local")
        first, _ = storage.publish(tree, {"device": "test"}, None)
        before = stats(storage.directory / "objects")
        added = copy.deepcopy(fixture["messages"][0])
        added["info"]["id"] = "msg_added_incremental"
        added["info"]["time"]["created"] += 100000
        added["parts"] = [{"id": "prt_added_incremental", "messageID": added["info"]["id"],
                           "sessionID": fixture["info"]["id"], "type": "text", "text": "one new message"}]
        fixture["messages"].append(added)
        chat._write(seed, fixture)
        chat._cli(["import", str(seed)], str(root))
        chat.capture(selection, tree.path(), str(root))
        second, _ = storage.publish(tree, {"device": "test"}, first)
        preserved = [name for name in first["artifacts"] if name.startswith(("messages/", "blobs/"))]
        self.assertTrue(preserved)
        for name in preserved:
            self.assertEqual(first["artifacts"][name], second["artifacts"][name])
        after = stats(storage.directory / "objects")
        self.assertLessEqual(len(set(after) - set(before)), 5)
        for name in set(before) & set(after):
            self.assertEqual(before[name], after[name])

    def test_native_family_round_trip_and_preservation(self):
        root = Path(os.environ["HOME"]) / "context"
        root.mkdir()
        (root / "external.txt").write_text("portable attachment")
        (root / "result.txt").write_text("full tool output")
        fixture = native_fixture(root)
        seed = self.base / "seed.json"

        def native_import(data, cwd):
            chat._write(seed, data)
            chat._cli(["import", str(seed)], str(cwd))

        native_import(fixture, root)
        child = chat._walk(copy.deepcopy(fixture), lambda value, trail:
                           value.replace("wsd", "child") if isinstance(value, str) else value)
        child["info"].update(id="ses_wsd1193child", parentID=fixture["info"]["id"])
        for message in child["messages"]:
            message["info"]["sessionID"] = child["info"]["id"]
            for part in message["parts"]:
                part["sessionID"] = child["info"]["id"]
        native_import(child, root)
        sid = fixture["info"]["id"]
        bundle = self.base / "bundle"
        manifest = chat.capture({"pid": os.getpid(), "session_id": sid, "directory": str(root)}, bundle, str(root))
        family = {sid, child["info"]["id"]}
        self.assertEqual({entry["id"] for entry in manifest["sessions"]}, family)
        self.assertGreaterEqual(len(manifest["files"]), 4)
        self.assertTrue(any("Git snapshot" in entry["reason"] for entry in manifest["unsupported"]))
        # Unchanged family/attachments are checked through read-only SQLite and
        # reused in RAM. Native CLI must not create routine logs/cache files.
        import checkpoint_store as store
        tree = store.Tree()
        tree.copy_from(bundle)
        before = dict(tree.files)
        with patch.object(chat, "_cli", side_effect=AssertionError("unchanged chat invoked native exporter")):
            reused = chat.capture({"session_id": sid, "directory": str(root)}, tree.path(), str(root))
        self.assertEqual(reused, manifest)
        self.assertEqual(tree.files, before)

        # Selecting a child must capture its parent and siblings/family, while
        # retaining that child as the selected session restored later.
        child_bundle = self.base / "child-bundle"
        selected_child = chat.capture({"session_id": child["info"]["id"]}, child_bundle, str(root))
        self.assertEqual({entry["id"] for entry in selected_child["sessions"]}, family)
        self.assertEqual(selected_child["selection"]["session_id"], child["info"]["id"])

        destination = self.environment("destination")
        destroot = destination / "context"
        destroot.mkdir()
        chat._cli(["session", "list"], str(destroot))
        # Actual bundle move and source removal prove blobs are self-contained.
        moved = self.base / "relocated-bundle"
        bundle.rename(moved)
        bundle = moved
        shutil.rmtree(root)
        local = chat.restore(bundle, str(destroot))
        self.assertNotEqual(local, sid)
        exported = chat._export(local, str(destroot))
        parts = exported["messages"][0]["parts"]
        self.assertTrue(parts[2]["url"].startswith("data:text/plain;base64,"))
        self.assertEqual(Path(parts[2]["source"]["path"]).read_text(), "portable attachment")
        assistant = exported["messages"][1]
        self.assertEqual(assistant["info"]["path"]["cwd"], str(destroot))
        tool = assistant["parts"][1]["state"]
        self.assertEqual(Path(tool["metadata"]["outputPath"]).read_text(), "full tool output")
        self.assertEqual(tool["attachments"][0]["url"], "data:image/png;base64,aW1hZ2UtYnl0ZXM=")
        child_id = assistant["parts"][2]["state"]["metadata"]["sessionId"]
        self.assertNotEqual(child_id, child["info"]["id"])
        self.assertEqual(chat._export(child_id, str(destroot))["info"]["parentID"], local)
        self.assertEqual(chat.restore(bundle, str(destroot)), local)
        self.assertEqual(set(chat._descendants(local, str(destroot))), {local, child_id})
        self.assertEqual(chat.restore(child_bundle, str(destroot)), child_id)

        fixture["messages"][0]["parts"][0]["text"] = "local newer"
        native_import(fixture, destroot)
        before = chat._export(sid, str(destroot))
        self.assertEqual(chat.restore(bundle, str(destroot)), local)
        self.assertEqual(chat._export(sid, str(destroot)), before)

        continued = chat._export(local, str(destroot))
        extra = copy.deepcopy(continued["messages"][0])
        extra["info"]["id"] = "msg_continued_local"
        extra["info"]["time"]["created"] += 10000
        extra["parts"] = [{"id": "prt_continued_local", "sessionID": local,
                           "messageID": "msg_continued_local", "type": "text", "text": "continued locally"}]
        continued["messages"].append(extra)
        native_import(continued, destroot)
        before = chat._export(local, str(destroot))
        replacement = chat.restore(bundle, str(destroot))
        self.assertNotEqual(replacement, local)
        self.assertEqual(chat.restore(bundle, str(destroot)), replacement)
        self.assertEqual(chat._export(local, str(destroot)), before)

        empty = self.base / "empty"
        chat.capture({"session_id": None}, empty, str(destroot))
        self.assertIsNone(chat.restore(empty, str(destroot)))
        exact = self.base / "exact"
        chat.capture({"session_id": replacement}, exact, str(destroot))
        self.assertEqual(chat.restore(exact, str(destroot)), replacement)
        next((bundle / "blobs").iterdir()).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "Corrupt chat artifact"):
            chat.restore(bundle, str(destroot))


@unittest.skipUnless(shutil.which("tmux") and shutil.which("node"), "tmux and node required")
@unittest.skipUnless(Path("/proc/self/stat").exists(), "Linux process metadata required")
class TuiSelectionTests(IsolatedChatTest):
    def test_route_switches_socket_ancestry_and_metadata(self):
        runtime = self.base / "runtime"
        runtime.mkdir(mode=0o700)
        route = runtime / "route.json"

        def set_route(value):
            pending = route.with_suffix(".pending")
            pending.write_text(json.dumps(value))
            pending.replace(route)

        set_route({"name": "session", "params": {"sessionID": "ses_first"}})
        mock = runtime / "mock.mjs"
        mock.write_text(
            f'import plugin from {json.dumps(PLUGIN.as_uri())};\n'
            'import {readFileSync} from "node:fs";\n'
            'const api={route:{get current(){return JSON.parse(readFileSync(process.env.ROUTE_FILE,"utf8"))}},'
            'state:{path:{directory:process.cwd()},session:{get(id){return {directory:process.cwd(),'
            'parentID:id==="ses_child"?"ses_parent":undefined}}}},'
            'lifecycle:{onDispose(fn){process.on("SIGTERM",()=>{fn();process.exit(0)})}}};\n'
            'await plugin.tui(api); setInterval(()=>{},1000);\n'
        )
        tmux = str(runtime / "tmux.sock")
        env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime), ROUTE_FILE=str(route))

        def run(*args):
            return subprocess.check_output(["tmux", "-S", tmux, *args], text=True, timeout=10)

        try:
            subprocess.run(["tmux", "-S", tmux, "new-session", "-d", "-s", "probe",
                            f"node {shlex.quote(str(mock))}"], cwd=self.base, env=env, check=True, timeout=10)
            pane, pid = run("display-message", "-p", "-t", "probe", "#{pane_id} #{pane_pid}").split()

            def poll(expected):
                last = None
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    option = run("show-option", "-pqv", "-t", pane, "@persistence-chat-socket").strip()
                    if option:
                        try:
                            last = chat.read_selection(Path(option), int(pid), tmux, pane)
                            if last["session_id"] == expected:
                                return last
                        except (ValueError, OSError) as error:
                            last = error
                    time.sleep(0.05)
                self.fail(f"Socket selection never became {expected!r}: {last!r}")

            self.assertEqual(poll("ses_first")["session_id"], "ses_first")
            set_route({"name": "session", "params": {"sessionID": "ses_child"}})
            self.assertEqual(poll("ses_child")["parent_id"], "ses_parent")
            set_route({"name": "home"})
            self.assertIsNone(poll(None)["session_id"])
            deadline = time.monotonic() + 5
            while True:
                option = json.loads(run("show-option", "-pqv", "-t", pane, "@persistence-chat"))
                if option["session_id"] is None:
                    break
                if time.monotonic() >= deadline:
                    self.fail(f"Home metadata not published: {option!r}")
                time.sleep(0.05)
            self.assertEqual(option["pid"], int(pid))
            endpoint = Path(run("show-option", "-pqv", "-t", pane, "@persistence-chat-socket").strip())
            with self.assertRaises(ValueError):
                chat.read_selection(endpoint, os.getpid(), tmux, pane)
        finally:
            subprocess.run(["tmux", "-S", tmux, "kill-server"], capture_output=True, timeout=10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
