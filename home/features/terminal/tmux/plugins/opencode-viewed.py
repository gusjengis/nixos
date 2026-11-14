"""A selected tmux pane is viewed only in the active desktop context."""
import json
import os
from pathlib import Path
import subprocess
import sys


def viewed(pane):
    output = subprocess.check_output(
        ["tmux", "display-message", "-p", "-t", pane,
         "#{session_attached}\t#{window_active}\t#{pane_active}\t#{session_name}"],
        text=True, timeout=1).strip()
    attached, window, active_pane, session = output.split("\t")
    if not (int(attached) > 0 and window == "1" and active_pane == "1"):
        return False
    if session.startswith("context-"):
        signature = os.environ["HYPRLAND_INSTANCE_SIGNATURE"]
        catalog = Path(os.environ["XDG_RUNTIME_DIR"]) / f"desktop-contexts-{signature}.json"
        active_context = json.loads(catalog.read_text()).get("active_context")
        return bool(active_context) and session == "context-" + active_context
    return True


def main():
    pane = sys.argv[1]
    clear = "--clear" in sys.argv[2:]
    try:
        is_viewed = viewed(pane)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        is_viewed = False  # Unknown visibility must not acknowledge unseen work.
    if not is_viewed:
        # A background pane is a successful no-op for focus hooks, but false
        # for callers querying visibility through the exit status.
        return 0 if clear else 1
    if clear:
        try:
            subprocess.run(["tmux", "if-shell", "-F", "-t", pane,
                            # Only completion is acknowledged by viewing; an error
                            # X persists until the next prompt resumes the session.
                            "#{==:#{@opencode_icon},!}",
                            f'set-option -p -t {pane} @opencode_icon ""'], check=True, timeout=1)
        except (OSError, subprocess.SubprocessError):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
