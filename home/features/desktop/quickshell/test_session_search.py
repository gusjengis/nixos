import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("universal_search", Path(__file__).with_name("universal-search.py"))
search = importlib.util.module_from_spec(spec)
with patch.dict(os.environ, QUICKSHELL_SEARCH_CONFIG="/unused/search.json"):
    spec.loader.exec_module(search)


class SessionSearchTests(unittest.TestCase):
    def setUp(self):
        self.workspace = "special:work-browser"
        self.run = self.enterContext(patch.object(search.subprocess, "run"))
        self.run.return_value = self.result("ok")
        self.popen = self.enterContext(patch.object(search.subprocess, "Popen"))
        self.special = self.enterContext(patch.object(search, "session_special", return_value=self.workspace))

    @staticmethod
    def result(stdout):
        return subprocess.CompletedProcess([], 0, stdout, "")

    def test_session_eval_accepts_only_ok(self):
        for output in ("ok", " \tok\n", "error: active session changed", "", "ok\nerror: failed"):
            with self.subTest(output=output):
                self.run.return_value = self.result(output)
                if output.strip() == "ok":
                    search.session_eval("statement")
                else:
                    with self.assertRaisesRegex(RuntimeError, "hyprctl eval failed"):
                        search.session_eval("statement")
                self.run.assert_called_with(["hyprctl", "eval", "statement"], capture_output=True, text=True)

    def test_terminal_exec_is_silent_and_unfocused(self):
        search.exec_on_workspace(["kitty", "tmux", "attach-session", "-t", "project name"], "special:work-terminal")

        command = self.run.call_args.args[0]
        self.assertEqual(command[:2], ["hyprctl", "dispatch"])
        self.assertIn('workspace = "special:work-terminal silent"', command[2])
        self.assertIn("no_initial_focus = true", command[2])
        self.assertIn("kitty tmux attach-session -t 'project name'", command[2])

    def test_absent_browser_launches_via_backend_then_guarded_show(self):
        url = "https://example.com/?q=one&next=two"
        with patch.object(search, "config", return_value={}), \
                patch.object(search, "chromium_window", side_effect=[None, "0x123"]) as window, \
                patch.object(search, "exec_on_workspace") as direct_exec:
            search.open_web(url)

        self.special.assert_called_once_with("browser")
        self.assertEqual(window.call_args_list, [unittest.mock.call(self.workspace)] * 2)
        statements = [call.args[0][2] for call in self.run.call_args_list]
        self.assertEqual(statements[0],
                         "require('sessions').launch_special('browser', "
                         f"{search.lua_string(shlex.join(['chromium', '--new-window', url]))}, "
                         f"{search.lua_string(self.workspace)})")
        self.assertEqual(statements[1],
                         "local sessions = require('sessions'); "
                         f"assert(sessions.special_name(\"browser\") == \"{self.workspace}\", 'active session changed'); "
                         'sessions.show_special("browser")')
        self.assertTrue(all(call.args[0][:2] == ["hyprctl", "eval"] for call in self.run.call_args_list))
        direct_exec.assert_not_called()
        self.popen.assert_not_called()

    def test_browser_launch_lua_error_stops_before_poll_or_show(self):
        self.run.return_value = self.result("error: active session changed")
        with patch.object(search, "config", return_value={}), \
                patch.object(search, "chromium_window", return_value=None) as window:
            with self.assertRaisesRegex(RuntimeError, "error: active session changed"):
                search.open_web("https://example.com")
        window.assert_called_once_with(self.workspace)
        self.run.assert_called_once()
        self.popen.assert_not_called()

    def test_tmux_client_ignores_more_recent_other_session(self):
        windows = [
            {"pid": 10, "workspace": {"address": "special:other-terminal", "name": "special:work-terminal"}},
            {"pid": 20, "workspace": {"address": "special:work-terminal", "name": "renamed"}},
        ]
        self.run.side_effect = [self.result(json.dumps(windows)), self.result("999\tother\t10\n1\tactive\t20\n")]
        with patch.object(search, "process_has_ancestor", side_effect=lambda pid, ancestors: pid in ancestors):
            self.assertEqual(search.terminal_tmux_client("special:work-terminal"), "active")

    def test_workspace_identity_prefers_address_with_name_fallback(self):
        for metadata, matches in (
            ({"address": self.workspace, "name": "renamed"}, True),
            ({"address": "special:other-browser", "name": self.workspace}, False),
            ({"name": self.workspace}, True),
            ({"address": None, "name": self.workspace}, True),
        ):
            with self.subTest(workspace=metadata):
                self.run.return_value = self.result(json.dumps([
                    {"address": "0x123", "class": "chromium", "workspace": metadata},
                ]))
                self.assertEqual(search.workspace_has_windows(self.workspace), matches)
                self.assertEqual(search.chromium_window(self.workspace), "0x123" if matches else None)


if __name__ == "__main__":
    unittest.main()
