import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("overview", Path(__file__).with_name("opencode-sessions.py"))
overview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(overview)


class SessionsTest(unittest.TestCase):
    def line(self, **fields):
        value = dict.fromkeys(overview.FIELDS, "")
        value.update(pane_id="%7", pane_pid=str(os.getpid()), pane_current_command="opencode",
                     session_id="$3", session_name="context-test", pane_current_path="/tmp")
        value.update(fields)
        return "\t".join(value[key] for key in overview.FIELDS)

    def test_live_idle_title_and_dead_tui_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "db.sqlite"
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE session (id TEXT, title TEXT)")
                db.execute("INSERT INTO session VALUES (?, ?)", ("chat", "Actual selected title"))
            selection = dict(pid=os.getpid(), pid_start_ticks=overview.start_ticks(os.getpid()),
                             database=str(database), session_id="chat", directory=directory)
            line = self.line(**{"@persistence-chat": json.dumps(selection)})
            item, = overview.collect(line)
            self.assertEqual(item["title"], "Actual selected title")
            self.assertEqual(item["state"], "idle")
            # A dead TUI's pane options must not make a shell look like a live chat.
            selection["pid_start_ticks"] = "wrong-start-time"
            self.assertEqual(overview.collect(self.line(pane_current_command="bash", **{
                "@persistence-chat": json.dumps(selection)})), [])

    def test_exact_plugin_status_and_colors(self):
        for icon, mode, state, color_key in [("?", "plan", "input", "question"),
                ("!", "build", "done", "success"), ("X", "build", "error", "error"),
                ("⠦", "plan", "working", "plan"), ("⠦", "retry", "working", "error")]:
            with self.subTest(icon=icon, mode=mode):
                item, = overview.collect(self.line(**{"@opencode_icon": icon, "@opencode_mode": mode,
                    f"@opencode_{color_key}_color": "#123456"}))
                self.assertEqual((item["state"], item["color"]), (state, "#123456"))

    def test_closed_row_cannot_reopen_chat(self):
        with patch.object(overview, "snapshot", return_value=[]), patch.object(overview.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Session closed"):
                overview.focus("%7")
            run.assert_not_called()

    def test_focus_uses_selected_chat_and_original_process_identity(self):
        item, = overview.collect(self.line())
        item["selection"] = dict(pid=123, pid_start_ticks="456", session_id="selected")
        with patch.object(overview, "snapshot", return_value=[item]), patch.object(overview.subprocess, "run") as run:
            overview.focus("%7")
            args = run.call_args.args[0]
            self.assertEqual(args[1], "--activate")
            self.assertEqual(args[6:10], ["selected", "%7", "$3", "context-test"])
            self.assertEqual(args[11:13], ["123", "456"])

    def test_focus_resolves_requested_client_not_invoking_client(self):
        handler = Path(__file__).parents[2] / "agents/opencode/session-notify/session-notify-handler.sh"
        source = handler.read_text()
        function = source.split("window_for_tmux_client() {", 1)[1].split("\nlatest_local_client_for_session()", 1)[0]
        # display-message intentionally reports the invoking client's PID. The
        # client list is authoritative, and only the requested PID owns target.
        script = '''
tmux() {
  if [[ $1 == list-clients ]]; then
    printf '/dev/pts/a\\t111\\n/dev/pts/b\\t222\\n'
  else printf '111'; fi
}
hyprland_clients() { printf '[{"pid":900,"address":"target"}]'; }
process_has_ancestor() { [[ $1 == 222 && $2 == 900 ]]; }
window_for_tmux_client() {''' + function + '\nwindow_for_tmux_client /dev/pts/b instance'
        result = subprocess.run(["bash", "-c", script], text=True, capture_output=True, timeout=3)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "target")

    def test_overview_suppresses_desktop_notification(self):
        handler = Path(__file__).parents[2] / "agents/opencode/session-notify/session-notify-handler.sh"
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "notification-spawned"
            for name, body in [("quickshell", "printf true"),
                               ("notify-send", f"touch '{marker}'; exit 99")]:
                executable = Path(directory) / name
                executable.write_text("#!/usr/bin/env bash\n" + body + "\n")
                executable.chmod(0o755)
            result = subprocess.run(["bash", str(handler), "Test", "Test", "normal", "/tmp"] + [""] * 8,
                                    env={**os.environ, "PATH": directory + ":" + os.environ["PATH"]},
                                    text=True, capture_output=True, timeout=3)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
