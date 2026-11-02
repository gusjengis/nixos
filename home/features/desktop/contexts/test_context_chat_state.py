"""Readiness/CAS tests use only isolated local state, never live OpenCode data."""
import multiprocessing
import json
import os
import socket
import shlex
from concurrent.futures import ThreadPoolExecutor
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import context_chat_state as state


def _publisher(path, owner):
    for number in range(10):
        state.publish(path, owner, "ses_chat", operation={"phase": "importing", "progress": number})


class StateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "state.json"

    def local(self):
        return state.publish(self.path, "owner", "ses_chat", selected_root="ses_native",
                             members={"ses_chat": "ses_native", "ses_child": "ses_native_child"},
                             known_revision="r1", base_revision="r1", freshness="current_as_known",
                             availability="local")

    def test_incoming_revision_revokes_local_selection_without_import(self):
        first = self.local()
        head = self.path.parent / "current.json"
        head.write_text("new head")
        updated = state.observe(self.path, "owner", "ses_chat", known_revision="r2",
                                observed_head=state.head_token(head), head_path=head,
                                source_device="laptop")
        self.assertGreater(updated["generation"], first["generation"])
        self.assertEqual(updated["freshness"], "outdated")
        self.assertEqual(updated["selected_root"], "ses_native")
        self.assertEqual(updated["members"], first["members"])
        self.assertEqual(updated["availability"], "local")
        self.assertEqual(updated["base_revision"], "r1")
        self.assertEqual(updated["source_device"], "laptop")

    def test_stale_worker_completion_cannot_promote_an_old_revision(self):
        first = self.local()
        state.observe(self.path, "owner", "ses_chat", known_revision="r2")
        with self.assertRaises(state.StateChanged):
            state.publish(self.path, "owner", "ses_chat", expected_generation=first["generation"],
                          base_revision="r1", freshness="current_as_known")
        with self.assertRaises(state.StateChanged):
            state.publish(self.path, "owner", "ses_chat", expected_revision="r1",
                          selected_root="ses_obsolete")
        self.assertEqual(state.get(self.path, "owner", "ses_chat")["freshness"], "outdated")

    def test_retry_availability_and_operation_do_not_erase_freshness_or_mapping(self):
        self.local()
        state.publish(self.path, "owner", "ses_chat", freshness="conflict")
        changed = state.observe(self.path, "owner", "ses_chat", known_revision="r2", availability="waiting_data")
        failed = state.publish(self.path, "owner", "ses_chat", operation={"phase": "failed", "error": "missing object"})
        self.assertEqual(failed["freshness"], "conflict")
        self.assertEqual(failed["selected_root"], changed["selected_root"])
        self.assertEqual(failed["availability"], "waiting_data")

    def test_noop_does_not_churn_generation_and_missing_is_not_empty_success(self):
        self.assertEqual(state.read(self.path)["generation"], 0)
        self.assertIsNone(state.get(self.path, "owner", "ses_chat"))
        first = self.local()
        again = state.publish(self.path, "owner", "ses_chat", availability="local")
        self.assertEqual(first["generation"], again["generation"])
        self.path.write_text('{"version":2}')
        with self.assertRaises(ValueError):
            state.read(self.path)
        with self.assertRaises(ValueError):
            self.local()

    def test_batch_publication_is_single_write_and_all_or_nothing(self):
        self.local()
        writes = []
        original = state._write
        with unittest.mock.patch.object(state, "_write", side_effect=lambda *a: (writes.append(1), original(*a))):
            records = state.observe_many(self.path, [
                {"owner": "owner", "chat": "ses_chat", "known_revision": "r2", "source_device": "laptop"},
                *({"owner": "owner", "chat": f"ses_new{n}", "known_revision": f"n{n}",
                   "availability": "portable_only"} for n in range(200))])
        self.assertEqual(len(writes), 1)
        self.assertEqual(records[0]["freshness"], "outdated")
        self.assertEqual(records[1]["freshness"], "unknown")
        self.assertEqual(len(state.read(self.path)["conversations"]), 201)
        generations = [record["generation"] for record in records]
        self.assertEqual(generations, sorted(set(generations)))
        before = state.read(self.path)
        with self.assertRaises(state.StateChanged):
            state.publish_many(self.path, [
                {"owner": "owner", "chat": "ses_new0", "operation": {"phase": "importing"}},
                {"owner": "owner", "chat": "ses_chat", "expected_revision": "r1", "selected_root": "ses_obsolete"}])
        self.assertEqual(state.read(self.path), before, "failed CAS must not publish earlier batch items")
        with unittest.mock.patch.object(state, "_write", side_effect=AssertionError("no-op batch wrote")):
            state.observe_many(self.path, [{"owner": "owner", "chat": "ses_new0", "known_revision": "n0",
                                            "availability": "portable_only"}])

    def test_concurrent_publishers_preserve_other_conversations_and_monotonic_generation(self):
        workers = [multiprocessing.Process(target=_publisher, args=(str(self.path), owner))
                   for owner in ("first", "second", "third")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
        snapshot = state.read(self.path)
        self.assertEqual(snapshot["generation"], 30)
        self.assertEqual(len(snapshot["conversations"]), 3)
        for record in snapshot["conversations"].values():
            self.assertEqual(record["operation"]["progress"], 9)


@unittest.skipUnless(os.environ.get("OC5_NATIVE_BINARY"), "set OC5_NATIVE_BINARY for isolated native HTTP proof")
class NativeGateTests(unittest.TestCase):
    def test_server_rejects_created_here_revision_without_persisting_stale_message(self):
        # Reuse OC1's isolated profile/provider fixture, not its TUI assertions.
        from opencode_acceptance_fixture import NativeFixture
        fixture = NativeFixture(os.environ["OC5_NATIVE_BINARY"], blocked=True)
        self.addCleanup(fixture.close)
        command_artifact = fixture.base / "command-must-not-run"
        configuration = json.loads(fixture.env["OPENCODE_CONFIG_CONTENT"])
        configuration["command"] = {"oc5probe": {"template": "!`touch " + shlex.quote(str(command_artifact)) + "`"}}
        fixture.env["OPENCODE_CONFIG_CONTENT"] = json.dumps(configuration)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        fixture.start(["serve", "--hostname", "127.0.0.1", "--port", str(port)])
        base = f"http://127.0.0.1:{port}"
        executor = ThreadPoolExecutor(max_workers=1)
        self.addCleanup(executor.shutdown, wait=False)

        def http_request(route, body=None):
            req = Request(base + route, data=json.dumps(body).encode() if body is not None else None,
                          headers={"Content-Type": "application/json", "x-opencode-directory": str(fixture.base / "work")})
            try:
                with urlopen(req, timeout=1 if route == "/global/health" else 30) as response:
                    return response.status, json.load(response)
            except HTTPError as error:
                try:
                    return error.code, error.read().decode()
                finally:
                    error.close()

        def request(route, body=None):
            pending = executor.submit(http_request, route, body)
            # Drain native PTY while instance initialization installs dependencies.
            # Otherwise a full terminal buffer can deadlock the HTTP caller.
            while not pending.done():
                fixture.pump()
            return pending.result()

        def healthy():
            try:
                return request("/global/health")[0] == 200
            except OSError:
                return False
        fixture.wait(healthy, "isolated native HTTP server ready", 30)
        code, session = request("/session", {"title": "OC5 isolated gate"})
        self.assertEqual(code, 200)
        marker = session["metadata"]["desktop_context"]
        route = "/session/" + session["id"] + "/message"
        code, first = request(route, {"parts": [{"type": "text", "text": "OC5_FIRST"}], "noReply": True})
        self.assertEqual(code, 200, first)
        self.assertFalse((fixture.base / "prepare-release").exists())
        path = fixture.env["OPENCODE_CONTEXT_STATE_FILE"]
        state.publish(path, marker["id"], marker["chat"], selected_root=session["id"],
                      members={marker["session"]: session["id"]}, known_revision="remote-r2", base_revision="local-r1",
                      availability="local", freshness="outdated")
        code, rejected = request(route, {"parts": [{"type": "text", "text": "OC5_STALE_MUST_NOT_SAVE"}], "noReply": True})
        self.assertGreaterEqual(code, 400, rejected)
        code, messages = request(route)
        self.assertEqual(code, 200)
        self.assertNotIn("OC5_STALE_MUST_NOT_SAVE", json.dumps(messages))
        self.assertIn("OC5_FIRST", json.dumps(messages))
        self.assertFalse(fixture.provider.requests, "noReply gate proof must never dispatch provider work")
        if os.environ.get("OC5_NATIVE_GUARDS") == "1":
            # These paths bypass chat.message (or execute template shell before
            # command.execute.before); only the new native entry guards cover them.
            shell_artifact = fixture.base / "shell-must-not-run"
            session_route = "/session/" + session["id"]
            code, rejected = request(session_route + "/shell", {
                "agent": "build", "command": "touch " + shlex.quote(str(shell_artifact))})
            self.assertGreaterEqual(code, 400, rejected)
            self.assertFalse(shell_artifact.exists())
            code, rejected = request(session_route + "/command", {"command": "oc5probe", "arguments": ""})
            self.assertGreaterEqual(code, 400, rejected)
            self.assertFalse(command_artifact.exists())
            code, messages = request(route)
            self.assertEqual(code, 200)
            self.assertNotIn("shell-must-not-run", json.dumps(messages))


if __name__ == "__main__":
    unittest.main()
