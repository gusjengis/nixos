"""Native OpenCode tool/permission acceptance using a local scripted model, no inference."""

import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import context_notes
import contextctl as ctl
import notebook


@unittest.skipUnless(os.environ.get("NOTEBOOK_OPENCODE_NATIVE") == "1", "opt-in native OpenCode fixture")
class NativeOpenCodeNotebookTests(unittest.TestCase):
    def test_owned_tools_and_plan_write_rejection(self):
        native = os.environ["NOTEBOOK_OPENCODE_BINARY"]
        with tempfile.TemporaryDirectory(prefix="notebook-opencode-", dir="/tmp/opencode") as directory:
            base = Path(directory)
            environment = {"CONTEXT_ROOT": str(base / "contexts"), "XDG_STATE_HOME": str(base / "state")}
            with patch.dict(os.environ, environment):
                context = ctl.create("Fixture", "/etc/nixos")
                context = ctl.find_context(context["id"])
                vault = context_notes.resolve(context["id"])
                vault.create({"title": "Desktop In-Progress widget", "body": "Behind windows. Keep my original wording.\n"})
            requests = []
            server_errors = []
            revision = None
            mode = "build"

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_args):
                    pass

                def do_POST(self):
                    nonlocal revision
                    try:
                        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                        requests.append(request)
                        messages = request["messages"]
                        outputs = [message for message in messages if message.get("role") == "tool"]
                        for result in outputs:
                            try:
                                parsed = json.loads(result["content"])
                                if parsed.get("revision"):
                                    revision = parsed["revision"]
                            except (ValueError, TypeError):
                                pass
                        actions = [
                            ("notebook_read", {"action": "brief"}),
                            ("notebook_read", {"action": "search", "query": "widget"}),
                            ("notebook_read", {"action": "read", "path": "Desktop In-Progress widget.md"}),
                            ("notebook_write", {"action": "update", "path": "Desktop In-Progress widget.md",
                                                "revision": revision, "status": "In-Progress", "work_state": "Next: render context-owned cards."}),
                            ("notebook_write", {"action": "create", "title": "Organizer Kanban preview", "body": "Later, show current work in the context organizer.", "status": "Thoughts"}),
                        ]
                        index = len(outputs)
                        if index < len(actions):
                            name, args = actions[index]
                            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": f"call_{index}",
                                "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}
                            finish = "tool_calls"
                        else:
                            delta, finish = {"role": "assistant", "content": "Notebook fixture finished."}, "stop"
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.end_headers()
                        for part, reason in ((delta, None), ({}, finish)):
                            chunk = {"id": "fixture", "object": "chat.completion.chunk", "created": int(time.time()),
                                     "model": "mock", "choices": [{"index": 0, "delta": part, "finish_reason": reason}]}
                            self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                        self.wfile.write(b"data: [DONE]\n\n")
                    except (ValueError, TypeError, KeyError, OSError) as exc:
                        server_errors.append(str(exc))
                        self.send_error(500)

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                for mode in ("build", "plan"):
                    requests.clear()
                    revision = None
                    config = {
                        "$schema": "https://opencode.ai/config.json", "model": "notebook-fixture/mock",
                        "small_model": "notebook-fixture/mock", "enabled_providers": ["notebook-fixture"],
                        "provider": {"notebook-fixture": {"npm": "@ai-sdk/openai-compatible", "name": "Local notebook fixture",
                            "options": {"baseURL": f"http://127.0.0.1:{server.server_port}/v1", "apiKey": "fixture"},
                            "models": {"mock": {"name": "mock", "tool_call": True, "limit": {"context": 131072, "output": 4096}}}}},
                    }
                    env = os.environ | environment | {"CONTEXT_ID": context["id"], "CONTEXT_DIRECTORY": context["path"],
                        "XDG_DATA_HOME": str(base / mode), "OPENCODE_CONFIG_CONTENT": json.dumps(config)}
                    env.pop("TMUX", None)
                    env.pop("TMUX_PANE", None)
                    result = subprocess.run([native, "run", "--format", "json", "--agent", mode,
                        "--model", "notebook-fixture/mock", "--title", "Notebook fixture",
                        "Exercise the notebook fixture: read my widget note, update its work state, and capture the organizer preview idea."],
                        cwd="/etc/nixos", env=env, text=True, capture_output=True, timeout=90, check=False)
                    self.assertEqual(result.returncode, 0, result.stderr[-3000:] + result.stdout[-3000:])
                    events = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
                    errors = [event.get("part", {}).get("state", {}) for event in events
                              if event.get("part", {}).get("state", {}).get("status") == "error"]
                    if mode == "build":
                        self.assertEqual(errors, [], errors)
                    self.assertFalse(server_errors, server_errors)
                    self.assertTrue(requests)
                    tools = {item["function"]["name"] for item in requests[0]["tools"]}
                    self.assertTrue({"notebook_read", "notebook_write"} <= tools)
                    system = "\n".join(str(message["content"]) for message in requests[0]["messages"] if message["role"] == "system")
                    self.assertIn("Context notebook", system)
                    self.assertIn(context["id"], system)
                    self.assertIn("Before replying, call notebook_read", system)
                    self.assertNotIn("Behind windows. Keep my original wording.", system)
                    with patch.dict(os.environ, environment):
                        card = context_notes.resolve(context["id"]).read({"path": "Desktop In-Progress widget.md"})
                    self.assertIn("Keep my original wording.", card["content"])
                    self.assertEqual(card["status"], "In-Progress")
                    _, metadata, _ = notebook.fields(card["content"])
                    self.assertEqual([event["status"] for event in metadata["kanban-history"]], ["Thoughts", "In-Progress"])
                    if mode == "plan":
                        self.assertIn("primary execution agent", result.stdout)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
