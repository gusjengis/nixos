#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shlex
import tempfile
import unittest
from unittest.mock import patch

import context_browser as browser


def client(address, rank, app="chromium-browser", **kwargs):
    return {"address": address, "focusHistoryID": rank, "class": app, **kwargs}


def snapshot():
    return {"active": "s1", "sessions": [
        {"id": "s1", "windows": ["0xa", "0xb", "0xc"]},
        {"id": "s2", "windows": ["0xd"]},
    ]}


class BrowserSelectionTests(unittest.TestCase):
    def test_current_context_mru_beats_global_mru(self):
        selected = browser.select_browser(snapshot(), [
            client("0xa", 8), client("0xb", 3), client("0xd", 0)])
        self.assertEqual(selected["address"], "0xb")

    def test_regular_workspace_browser_is_eligible(self):
        selected = browser.select_browser(snapshot(), [
            client("0xa", 1, workspace={"name": "session-s1-output-4"})])
        self.assertEqual(selected["address"], "0xa")

    def test_webapps_and_other_contexts_are_not_browsers(self):
        self.assertIsNone(browser.select_browser(snapshot(), [
            client("0xa", 0, "chrome-calendar.google.com__-Default"),
            client("0xd", 1)]))

    def test_unmapped_and_unfocused_windows_do_not_beat_mru(self):
        selected = browser.select_browser(snapshot(), [
            client("0xa", -1), client("0xb", 2, "Chromium"),
            client("0xc", 0, mapped=False)])
        self.assertEqual(selected["address"], "0xb")

    def test_closing_or_missing_context_fails(self):
        value = snapshot()
        value["sessions"][0]["closing"] = True
        with self.assertRaises(browser.contexts.ContextError):
            browser.select_browser(value, [])
        value["active"] = "missing"
        with self.assertRaises(browser.contexts.ContextError):
            browser.select_browser(value, [])


class BrowserRoutingTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "sessions.json"
        self.path.write_text(json.dumps(snapshot()))
        for name, replacement in [
            ("runtime_path", lambda _: self.path),
            ("clients", lambda: []),
            ("process_profile", lambda _: None),
        ]:
            patcher = patch.object(browser.contexts, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.evaluate = self.enter(patch.object(browser.contexts, "evaluate"))
        self.spawn = self.enter(patch.object(browser.subprocess, "Popen"))
        self.enter(patch.object(browser.time, "sleep"))
        self.enter(patch.dict(os.environ, {"CONTEXT_BROWSER_ENABLED": "1"}))

    def enter(self, patcher):
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def decoded_calls(self):
        # contextctl's Lua strings use decimal UTF-8 byte escapes.
        import re
        return [re.sub(r"(?:\\[0-9]{3})+", lambda m: bytes(
            int(n) for n in re.findall(r"\\([0-9]{3})", m[0])).decode(), call.args[0])
            for call in self.evaluate.call_args_list]

    def test_absent_browser_creates_on_current_browser_workspace(self):
        browser.open_links(["https://example.com/"])
        statement, = self.decoded_calls()
        self.assertIn('s.state().active=="s1"', statement)
        self.assertIn("s.launch_special('browser'", statement)
        self.assertIn('"special:session-s1-browser"', statement)
        self.assertIn("--new-window -- https://example.com/", statement)
        self.assertIn("s.show_special('browser')", statement)
        self.spawn.assert_not_called()

    def test_existing_browser_focuses_then_rechecks_before_url_handoff(self):
        self.enter(patch.object(browser.contexts, "clients", return_value=[client("0xb", 4), client("0xd", 0)]))
        browser.open_links(["https://example.com/"])
        focus, launch = self.decoded_calls()
        self.assertIn('s.focus_window("address:0xb")', focus)
        self.assertNotIn("exec_cmd", focus)
        self.assertIn('w.address=="0xb"', launch)
        self.assertIn("Browser left current context", launch)
        self.assertIn("--new-tab -- https://example.com/", launch)
        self.assertNotIn("launch_special", launch)

    def test_url_shell_metacharacters_are_data(self):
        url = "https://example.com/?x='; touch /bad; #"
        browser.open_links([url, "https://example.org/"])
        statement, = self.decoded_calls()
        self.assertIn(shlex.quote(url), statement)
        self.assertIn("env -u XDG_ACTIVATION_TOKEN -u DESKTOP_STARTUP_ID", statement)

    def test_launcher_without_urls_only_focuses_existing_browser(self):
        self.enter(patch.object(browser.contexts, "clients", return_value=[client("0xa", 1)]))
        browser.open_links([])
        statement, = self.decoded_calls()
        self.assertIn('s.focus_window("address:0xa")', statement)
        self.assertNotIn("exec_cmd", statement)

    def test_focus_race_fails_without_global_fallback(self):
        self.enter(patch.object(browser.contexts, "clients", return_value=[client("0xa", 1)]))
        self.evaluate.side_effect = [None, browser.contexts.ContextError("Browser focus changed")]
        with self.assertRaises(browser.contexts.ContextError):
            browser.open_links(["https://example.com/"])
        self.spawn.assert_not_called()

    def test_missing_context_state_fails_closed(self):
        self.path.unlink()
        with self.assertRaises(browser.contexts.ContextError):
            browser.open_links(["https://example.com/"])
        self.spawn.assert_not_called()

    def test_disabled_contexts_keep_standard_browser_launch(self):
        with patch.dict(os.environ, {"CONTEXT_BROWSER_ENABLED": "0"}):
            browser.open_links(["https://example.com/"])
        self.spawn.assert_called_once()
        self.evaluate.assert_not_called()

    def test_separate_user_data_directory_is_preserved(self):
        self.enter(patch.object(browser.contexts, "clients", return_value=[client("0xa", 1, pid=42)]))
        self.enter(patch.object(browser.contexts, "process_profile", return_value="/home/test/custom profile"))
        browser.open_links(["https://example.com/"])
        self.assertIn(shlex.quote("--user-data-dir=/home/test/custom profile"), self.decoded_calls()[1])


if __name__ == "__main__":
    unittest.main()
