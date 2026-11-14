"""Read only live tmux TUI selections; reuse status-plugin presentation state."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys


FIELDS = ["pane_id", "pane_pid", "pane_current_command", "session_id", "session_name",
          "pane_current_path", "@opencode_icon", "@opencode_mode", "@persistence-chat",
          "@opencode_build_color", "@opencode_plan_color", "@opencode_question_color",
          "@opencode_success_color", "@opencode_error_color",
          "@persistence-close-staging", "@persistence-close-staged"]


def run(args):
    return subprocess.check_output(args, text=True, timeout=2).strip()


def start_ticks(pid):
    try:
        return Path(f"/proc/{int(pid)}/stat").read_text().rsplit(") ", 1)[1].split()[19]
    except (OSError, ValueError, IndexError, TypeError):
        return None


def descendant(pid, ancestor):
    try:
        while int(pid) > 1:
            if int(pid) == int(ancestor):
                return True
            pid = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(") ", 1)[1].split()[1]
    except (OSError, ValueError, IndexError, TypeError):
        pass
    return False


def title_for(selection):
    """Return a title only for a selected chat with persisted messages."""
    if not selection.get("session_id") or not selection.get("database"):
        return None
    try:
        uri = Path(selection["database"]).as_uri() + "?mode=ro"
        with closing(sqlite3.connect(uri, uri=True, timeout=0.1)) as db:
            native = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_v2'").fetchone()
            sessions, messages = ("session_v2", "session_message") if native else ("session", "message")
            row = db.execute(f"""SELECT title FROM {sessions} WHERE id = ?
                AND EXISTS (SELECT 1 FROM {messages} WHERE session_id = {sessions}.id)""",
                (selection["session_id"],)).fetchone()
            return (row[0] or "Untitled session") if row else None
    except (sqlite3.Error, ValueError):
        return None


def collect(output):
    sessions = []
    for line in output.splitlines():
        values = line.split("\t")
        if len(values) != len(FIELDS):
            continue
        pane = dict(zip(FIELDS, values))
        # Closed tabs may stay alive privately while capture finishes or awaits
        # recovery. They are no longer navigable sessions, even with a live TUI.
        if (pane["session_name"].startswith("__context_closing_")
                or pane["@persistence-close-staging"] == "1"
                or pane["@persistence-close-staged"] == "1"):
            continue
        try:
            selection = json.loads(pane["@persistence-chat"] or "{}")
        except (ValueError, TypeError):
            selection = {}
        live = (bool(selection.get("pid_start_ticks"))
                and start_ticks(selection.get("pid")) == selection["pid_start_ticks"]
                and descendant(selection.get("pid"), pane["pane_pid"]))
        if not live:
            continue
        title = title_for(selection)
        if title is None:
            continue
        icon, mode = pane["@opencode_icon"], pane["@opencode_mode"]
        state = {"?": "input", "!": "done", "X": "error", "": "idle"}.get(icon, "working")
        color_key = {"input": "question", "done": "success", "error": "error"}.get(state,
            "error" if mode == "retry" else "plan" if mode == "plan" else "build")
        color = pane[f"@opencode_{color_key}_color"]
        if not color.startswith("#"):
            color = {"question": "#d29922", "success": "#3fb950", "error": "#f85149",
                     "plan": "#e3b341", "build": "#bc8cff"}[color_key]
        sessions.append({"pane": pane["pane_id"], "tmux_session": pane["session_id"],
                         "tmux_name": pane["session_name"], "selection": selection,
                         "directory": selection.get("directory") or pane["pane_current_path"],
                          "title": title, "state": state, "mode": mode,
                         # Animate in QML at the plugin's 80ms cadence without
                         # rebuilding rows for each sampled tmux spinner frame.
                         "icon": "⠋" if state == "working" else icon,
                         "color": color if state != "idle" else "#8e8e93"})
    return sessions


def snapshot():
    try:
        output = run(["tmux", "list-panes", "-a", "-F", "\t".join("#{" + key + "}" for key in FIELDS)])
    except subprocess.CalledProcessError:
        return []
    return collect(output)


def focus(pane):
    # Resolve again at click time. Never launch a stale or already-closed chat.
    session = next((item for item in snapshot() if item["pane"] == pane), None)
    if not session:
        raise RuntimeError("Session closed")
    selection = session["selection"]
    subprocess.run(["opencode-session-notify", "--activate", "", "", "normal", session["directory"],
         selection.get("session_id") or "", pane, session["tmux_session"], session["tmux_name"], "",
         str(selection.get("pid") or ""), str(selection.get("pid_start_ticks") or ""), ""], check=True, timeout=15)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "focus":
            focus(sys.argv[2])
        else:
            print(json.dumps(snapshot()))
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
