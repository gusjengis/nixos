"""Real PTY -> submitted message -> local provider, opt-in native acceptance."""

import json
import os
import sqlite3
import math
import time
import unittest
import uuid
from contextlib import closing

from opencode_acceptance_fixture import NativeFixture, Screen


class ScreenTests(unittest.TestCase):
    def test_erased_prompt_is_not_submitted_message_proof(self):
        screen = Screen(4, 40)
        screen.feed(b"typing-only\x1b[1;1H\x1b[2Ksubmitted")
        self.assertNotIn("typing-only", screen.text)
        self.assertIn("submitted", screen.text)
        screen.feed(b"\x1b[2J\x1b[1;1Hnew")
        self.assertNotIn("submitted", screen.text)
        self.assertTrue(screen.lines[0].startswith("new"))


@unittest.skipUnless(os.environ.get("OPENCODE_ACCEPTANCE_NATIVE") == "1", "set OPENCODE_ACCEPTANCE_NATIVE=1")
class NativeAcceptanceTests(unittest.TestCase):
    def exercise(self, *, launcher, blocked, fixture=None):
        binary = os.environ["OPENCODE_ACCEPTANCE_BINARY"]
        if fixture is None:
            fixture = NativeFixture(binary, launcher=launcher, blocked=blocked)
            self.addCleanup(fixture.close)
        else:
            fixture.reset()
        fixture.start()
        fixture.wait(lambda: "Ask anything" in fixture.screen.text and fixture.tui().get("ready"), "native prompt and TUI observer ready", 30)
        if blocked:
            fixture.wait(lambda: (fixture.base / "prepare-started").exists(), "preparation entered helper")
            self.assertFalse((fixture.base / "prepare-release").exists())
        token = "OC1_SENT_" + uuid.uuid4().hex[:12]
        fixture.write(token)
        typing = fixture.wait(lambda: token in fixture.screen.text, "typed sentinel rendered")
        submitted = time.monotonic()
        fixture.write("\r")
        accepted = fixture.wait(lambda: fixture.accepted(token), "actual submitted user message in TUI state", 8)
        # A distinct unsent draft disambiguates composer echo from submitted history.
        draft = "OC1_UNSENT_DRAFT"
        fixture.write(draft)
        visible = fixture.wait(lambda: token in fixture.screen.text and draft in fixture.screen.text,
                               "submitted history and distinct new draft rendered together", 5)
        fixture.wait(lambda: fixture.provider.matching(token), "scripted provider received submitted prompt", 8)
        lines = fixture.screen.lines
        self.assertLess(next(i for i, line in enumerate(lines) if token in line),
                        next(i for i, line in enumerate(lines) if draft in line))
        self.assertEqual(len(fixture.accepted(token)), 1)
        self.assertFalse(fixture.accepted(draft))
        self.assertFalse(fixture.provider.matching(draft))
        self.assertFalse(fixture.provider.release.is_set(), "provider response must remain blocked during proof")
        if blocked:
            self.assertFalse((fixture.base / "prepare-release").exists(), "fresh send depended on preparation release")
        receipt = fixture.provider.matching(token)[0]["at"]
        result = {"case": "launcher" if launcher else "native", "blocked_preparation": blocked,
                  "launch_to_typing_ms": round((typing - fixture.started) * 1000, 2),
                  "submit_to_message_ms": round((accepted - submitted) * 1000, 2),
                  "submit_to_provider_ms": round((receipt - submitted) * 1000, 2),
                  "submit_to_history_and_new_draft_ms": round((visible - submitted) * 1000, 2)}
        result["budgets_pass"] = result["submit_to_history_and_new_draft_ms"] <= 500 and result["submit_to_provider_ms"] <= 1000
        print("OC1_RESULT " + json.dumps(result), flush=True)
        results_file = os.environ.get("OPENCODE_ACCEPTANCE_RESULTS")
        if results_file:
            with open(results_file, "a") as output:
                output.write(json.dumps(result) + "\n")
        # Behavior is always enforced. Budget enforcement is an explicit gate,
        # distinct from instrument validation on a busy shared build machine.
        if os.environ.get("OPENCODE_ACCEPTANCE_ENFORCE_TIMING") == "1":
            self.assertLess(visible - submitted, .5, result)
            self.assertLess(receipt - submitted, 1, result)
        while time.monotonic() - receipt < 2:
            fixture.pump()
        self.assertNotIn("OC1 provider completed.", fixture.screen.text)
        fixture.provider.release.set()
        fixture.wait(lambda: "OC1 provider completed." in fixture.screen.text, "scripted provider response rendered", 8)
        return fixture, result

    @unittest.skipUnless(int(os.environ.get("OPENCODE_ACCEPTANCE_BENCHMARK_PAIRS", "0")), "set OPENCODE_ACCEPTANCE_BENCHMARK_PAIRS=20")
    def test_paired_warm_performance(self):
        count = int(os.environ["OPENCODE_ACCEPTANCE_BENCHMARK_PAIRS"])
        native, _ = self.exercise(launcher=False, blocked=True)
        native.stop()
        launcher, _ = self.exercise(launcher=True, blocked=True)
        launcher.stop()
        pairs = []
        for number in range(count):
            results = {}
            modes = [("native", native), ("launcher", launcher)]
            if number % 2:
                modes.reverse()
            for label, fixture in modes:
                _, result = self.exercise(launcher=fixture.launcher, blocked=True, fixture=fixture)
                results[label] = result
                fixture.stop()
            pairs.append(results)
        metrics = ["launch_to_typing_ms", "submit_to_message_ms", "submit_to_provider_ms", "submit_to_history_and_new_draft_ms"]
        percentile = lambda values: sorted(values)[math.ceil(.95 * len(values)) - 1]
        overhead = {metric: round(percentile([pair["launcher"][metric] - pair["native"][metric] for pair in pairs]), 2)
                    for metric in metrics}
        absolute = {metric: round(percentile([pair["launcher"][metric] for pair in pairs]), 2) for metric in metrics}
        report = {"warm_pairs": count, "p95_paired_overhead_ms": overhead, "launcher_p95_ms": absolute,
                  "integration_budget_pass": all(value <= 500 for value in overhead.values()),
                  "absolute_budget_pass": absolute["launch_to_typing_ms"] <= 5000 and
                  absolute["submit_to_history_and_new_draft_ms"] <= 500 and absolute["submit_to_provider_ms"] <= 1000}
        print("OC1_BENCHMARK " + json.dumps(report), flush=True)
        self.assertTrue(report["integration_budget_pass"], report)
        if os.environ.get("OPENCODE_ACCEPTANCE_ENFORCE_TIMING") == "1":
            self.assertTrue(report["absolute_budget_pass"], report)

    def test_native_fresh_send_blocked_preparation(self):
        self.exercise(launcher=False, blocked=True)

    def test_launcher_fresh_send_blocked_preparation(self):
        self.exercise(launcher=True, blocked=True)

    def test_launcher_fresh_send_normal(self):
        self.exercise(launcher=True, blocked=False)

    def test_created_here_chat_rechecks_new_revision_before_next_send(self):
        fixture, _ = self.exercise(launcher=True, blocked=True)
        session = fixture.tui()["session"]
        fixture.publish_state(known_revision="remote-v2", base_revision="local-v1",
                              selected_root="ses_verified_newer", members={}, freshness="outdated",
                              availability="local", source_device="fixture-B", operation={"phase": "idle"})
        token = "OC1_STALE_" + uuid.uuid4().hex[:12]
        fixture.write("\x15" + token)
        fixture.wait(lambda: token in fixture.screen.text, "stale send draft typed")
        fixture.write("\r")
        # Installed binary: server rejection toast. Integrated: blocking overlay.
        fixture.wait(lambda: "Failed to send prompt" in fixture.screen.text or
                     "Newer conversation" in fixture.screen.text,
                     "visible rejection/blocking for known stale send", 5)
        self.assertFalse(fixture.provider.matching(token), "known stale content dispatched")
        self.assertFalse(fixture.accepted(token), "known stale content persisted")
        self.assertEqual(fixture.tui()["session"]["id"], session["id"])

    def test_unchanged_existing_chat_sends_while_preparation_blocked(self):
        fixture, _ = self.exercise(launcher=True, blocked=True)
        session = fixture.tui()["session"]
        marker = session["metadata"]["desktop_context"]
        fixture.publish_state(known_revision="v1", base_revision="v1", selected_root=session["id"],
                              members={marker["session"]: session["id"]}, freshness="current_as_known",
                              availability="local", operation={"phase": "idle"})
        token = "OC1_EXISTING_" + uuid.uuid4().hex[:12]
        fixture.write("\x15" + token)
        fixture.wait(lambda: token in fixture.screen.text, "existing chat continuation typed")
        start = time.monotonic()
        fixture.write("\r")
        fixture.wait(lambda: fixture.accepted(token), "unchanged chat accepted with blocked preparation", 8)
        fixture.wait(lambda: fixture.provider.matching(token), "existing chat provider dispatch", 8)
        self.assertFalse((fixture.base / "prepare-release").exists())
        print("OC1_CONTINUATION " + json.dumps({"submit_to_provider_ms": round((fixture.provider.matching(token)[0]["at"] - start) * 1000, 2)}), flush=True)

    def portable_pair(self, count=2, **destination_options):
        """Device A publishes; device B receives archive bytes only (no DB/ledger)."""
        from test_chat_portability import native_fixture
        binary = os.environ["OPENCODE_ACCEPTANCE_BINARY"]
        source = NativeFixture(binary, blocked=False)
        self.addCleanup(source.close)
        destination = NativeFixture(binary, blocked=False, **destination_options)
        self.addCleanup(destination.close)
        origins = []
        for number in range(count):
            root = source.base / "work"
            (root / "external.txt").write_text("fixture attachment")
            (root / "result.txt").write_text("fixture result")
            chat = native_fixture(root)
            origin = f"ses_oc1portable{number}"
            origins.append(origin)
            chat = json.loads(json.dumps(chat).replace(chat["info"]["id"], origin))
            chat["info"]["title"] = f"OC1 portable {number}"
            chat["info"]["metadata"] = {"desktop_context": {"id": source.context["id"], "chat": origin, "session": origin}}
            seed = source.base / f"seed{number}.json"
            seed.write_text(json.dumps(chat))
            result = source.native("import", str(seed))
            self.assertEqual(result.returncode, 0, result.stderr)
        result = source.cli("sync", timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        destination.mirror_from(source)
        return source, destination, origins

    def edit_and_publish(self, source, origin, title):
        # Fixture-only native projection mutation, then real portable publication.
        with closing(sqlite3.connect(source.env["OPENCODE_DB"])) as db, db:
            db.execute("UPDATE session SET title=?, time_updated=time_updated+1000 WHERE id=?", (title, origin))
        result = source.cli("sync", timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)

    def open_received_copy(self, destination, owner, origin):
        result = destination.cli("ensure", "--owner", owner, "--chat", origin, timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = json.loads(result.stdout)
        destination.start(["--session", selected["session_id"]])
        destination.wait(lambda: (destination.tui().get("session") or {}).get("id") == selected["session_id"]
                         and "OC1 portable" in destination.screen.text, "received copy open in TUI", 40)
        return selected

    def test_late_remote_update_blocks_send_on_received_copy(self):
        source, destination, origins = self.portable_pair(1)
        owner = source.context["id"]
        selected = self.open_received_copy(destination, owner, origins[0])
        draft = "OC1_LATE_" + uuid.uuid4().hex[:12]
        destination.write(draft)
        destination.wait(lambda: draft in destination.screen.text, "draft typed on received copy")
        self.edit_and_publish(source, origins[0], "OC1 edited on device A")
        delivered = time.monotonic()
        destination.mirror_from(source)
        # Real background discovery (no manual helper call) must notice the head.
        detected = destination.wait(lambda: self.state_record(destination, owner, origins[0]),
                                    "outdated state after delivery", 15)
        destination.write("\r")
        destination.wait(lambda: "Failed to send prompt" in destination.screen.text or "Newer conversation" in destination.screen.text,
                         "visible rejection/blocking of stale send", 5)
        end = time.monotonic() + 2
        while time.monotonic() < end:
            destination.pump()
        self.assertFalse(destination.provider.matching(draft), "send dispatched after newer revision arrived")
        self.assertFalse(destination.accepted(draft), "stale message persisted")
        with closing(sqlite3.connect(destination.env["OPENCODE_DB"])) as db:
            self.assertIn((selected["session_id"],), db.execute("SELECT id FROM session").fetchall())
        print("OC1_LATE_UPDATE " + json.dumps({"delivery_to_outdated_ms": round((detected - delivered) * 1000, 2)}), flush=True)

    def state_record(self, fixture, owner, chat):
        try:
            with open(fixture.env["OPENCODE_CONTEXT_STATE_FILE"]) as handle:
                value = json.load(handle)
        except (OSError, ValueError):
            return None
        record = value.get("conversations", {}).get(f"{owner}/{chat}")
        return record if record and record.get("freshness") == "outdated" else None

    @unittest.skipUnless(os.environ.get("OPENCODE_ACCEPTANCE_INTEGRATED") == "1", "needs integrated native binary (stale/history patches)")
    def test_integrated_stale_overlay_blocks_and_opens_latest_with_draft(self):
        source, destination, origins = self.portable_pair(1, tui_plugins=("context-stale.tsx",))
        owner = source.context["id"]
        selected = self.open_received_copy(destination, owner, origins[0])
        draft = "OC1_OVERLAY_" + uuid.uuid4().hex[:12]
        destination.write(draft)
        destination.wait(lambda: draft in destination.screen.text, "draft typed")
        self.edit_and_publish(source, origins[0], "OC1 edited on device A")
        delivered = time.monotonic()
        destination.mirror_from(source)
        shown = destination.wait(lambda: "Newer conversation" in destination.screen.text, "blocking overlay", 15)
        destination.write("\x1b")
        end = time.monotonic() + 1
        while time.monotonic() < end:
            destination.pump()
        self.assertIn("Newer conversation", destination.screen.text, "Escape dismissed blocking overlay")
        self.assertEqual(destination.tui()["session"]["id"], selected["session_id"], "silent route switch")
        destination.write("\r")
        switched = destination.wait(lambda: (destination.tui().get("session") or {}).get("id") not in (None, selected["session_id"])
                                    and "Newer conversation" not in destination.screen.text, "opened latest verified copy", 60)
        destination.wait(lambda: draft in destination.screen.text, "draft carried to latest copy", 5)
        self.assertIn("OC1 edited on device A", json.dumps(destination.tui()["session"]))
        self.assertFalse(destination.provider.matching(draft))
        with closing(sqlite3.connect(destination.env["OPENCODE_DB"])) as db:
            ids = {row[0] for row in db.execute("SELECT id FROM session")}
        self.assertIn(selected["session_id"], ids, "superseded history removed")
        print("OC1_OVERLAY " + json.dumps({"delivery_to_overlay_ms": round((shown - delivered) * 1000, 2),
                                         "acknowledge_to_latest_ms": round((switched - shown) * 1000, 2)}), flush=True)

    @unittest.skipUnless(os.environ.get("OPENCODE_ACCEPTANCE_INTEGRATED") == "1", "needs integrated native binary (stale/history patches)")
    def test_integrated_history_picker_lists_portable_and_opens_selected(self):
        source, destination, origins = self.portable_pair(2, tui_plugins=("context-library.tsx",))
        destination.start()
        destination.wait(lambda: "Ask anything" in destination.screen.text and destination.tui().get("ready"), "home prompt", 40)
        opened = time.monotonic()
        destination.write("/sessions")
        destination.wait(lambda: "/sessions" in destination.screen.text, "command typed")
        destination.write("\r")
        listed = destination.wait(lambda: "OC1 portable 0" in destination.screen.text and "OC1 portable 1" in destination.screen.text,
                                  "portable-only summaries in picker", 10)
        self.assertFalse(os.path.exists(destination.env["OPENCODE_DB"]) and self.native_count(destination),
                         "picker hydrated histories")
        destination.write("OC1 portable 1")
        destination.wait(lambda: "OC1 portable 0" not in destination.screen.text, "filtered")
        destination.write("\r")
        ready = destination.wait(lambda: (destination.tui().get("session") or {}).get("title") == "OC1 portable 1",
                                 "selected portable conversation opened", 60)
        self.assertEqual(self.native_count(destination), 1, "unselected conversation imported")
        print("OC1_HISTORY " + json.dumps({"picker_to_summaries_ms": round((listed - opened) * 1000, 2),
                                         "selection_to_ready_ms": round((ready - listed) * 1000, 2)}), flush=True)

    def native_count(self, fixture):
        with closing(sqlite3.connect(fixture.env["OPENCODE_DB"])) as db:
            return db.execute("SELECT count(*) FROM session").fetchone()[0]

    def test_two_isolated_devices_portable_list_selected_import_and_idempotence(self):
        from test_chat_portability import native_fixture
        binary = os.environ["OPENCODE_ACCEPTANCE_BINARY"]
        source, destination = NativeFixture(binary, blocked=False), NativeFixture(binary, blocked=False)
        self.addCleanup(source.close)
        self.addCleanup(destination.close)
        origins = []
        for number in range(2):
            root = source.base / "work"
            (root / "external.txt").write_text("fixture attachment")
            (root / "result.txt").write_text("fixture result")
            chat = native_fixture(root)
            origin = f"ses_oc1portable{number}"
            origins.append(origin)
            # Replace all fixture-local references consistently, including parts.
            chat = json.loads(json.dumps(chat).replace(chat["info"]["id"], origin))
            chat["info"]["title"] = f"OC1 portable {number}"
            chat["info"]["metadata"] = {"desktop_context": {"id": source.context["id"], "chat": origin, "session": origin}}
            seed = source.base / f"seed{number}.json"
            seed.write_text(json.dumps(chat))
            result = source.native("import", str(seed))
            self.assertEqual(result.returncode, 0, result.stderr)
        result = source.cli("sync", timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        destination.mirror_from(source)
        start = time.monotonic()
        result = destination.cli("list")
        self.assertEqual(result.returncode, 0, result.stderr)
        listing = json.loads(result.stdout)
        self.assertEqual({item["chat"] for item in listing["conversations"]}, set(origins))
        self.assertTrue(all(item["state"]["availability"] == "portable_only" for item in listing["conversations"]))
        self.assertFalse(os.path.exists(destination.env["OPENCODE_DB"]), "listing hydrated portable histories")
        list_ms = (time.monotonic() - start) * 1000
        start = time.monotonic()
        result = destination.cli("ensure", "--owner", source.context["id"], "--chat", origins[0], timeout=90)
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = json.loads(result.stdout)
        self.assertEqual(selected["freshness"], "current_as_known")
        self.assertEqual(selected["availability"], "local")
        ensure_ms = (time.monotonic() - start) * 1000
        with closing(sqlite3.connect(destination.env["OPENCODE_DB"])) as db:
            before = db.execute("SELECT id FROM session").fetchall()
        self.assertEqual(len(before), 1, "unselected family was imported")
        again = destination.cli("ensure", "--owner", source.context["id"], "--chat", origins[0])
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(json.loads(again.stdout)["session_id"], selected["session_id"])
        with closing(sqlite3.connect(destination.env["OPENCODE_DB"])) as db:
            self.assertEqual(db.execute("SELECT id FROM session").fetchall(), before)
        exported = destination.native("export", selected["session_id"])
        self.assertEqual(exported.returncode, 0, exported.stderr)
        self.assertEqual(len(json.loads(exported.stdout)["messages"]), 4)
        self.assertEqual(len(source.provider.requests) + len(destination.provider.requests), 0)
        print("OC1_PORTABILITY " + json.dumps({"list_ms": round(list_ms, 2), "selected_import_ms": round(ensure_ms, 2),
                                             "unselected_imports": 0, "idempotent": True}), flush=True)


if __name__ == "__main__":
    unittest.main()
