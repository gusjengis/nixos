"""Best-effort checkpoint before compositor exit; saving never vetoes exit."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import time

CHECKPOINT_TIMEOUT = 30


def event_log():
    try:
        root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
        path = root / "desktop-contexts/terminal/events.log"
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path.open("a")
    except OSError:
        return None  # stderr is captured by the session journal.


def report(message, stream=None):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {message}"
    print(line, file=sys.stderr, flush=True)
    if stream is not None:
        try:
            print(line, file=stream, flush=True)
        except OSError:
            pass


def main():
    stream = event_log()
    process = None
    try:
        report("Compositor exit requested; attempting checkpoint (maximum 30s)", stream)
        try:
            process = subprocess.Popen(
                ["context-checkpoint", "save", "--reason", "compositor-exit"],
                stdout=stream, stderr=stream, start_new_session=True,
            )
            status = process.wait(timeout=CHECKPOINT_TIMEOUT)
            if status:
                report(f"Compositor-exit checkpoint failed (status {status}); exiting anyway; previous checkpoint retained", stream)
        except Exception as exc:
            report(f"Compositor-exit checkpoint failed: {exc}; exiting anyway; previous checkpoint retained", stream)
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=2)
    except Exception as exc:
        report(f"Compositor-exit preparation failed: {exc}; exiting anyway")
    finally:
        try:
            if stream is not None:
                stream.close()
        except OSError:
            pass
        # Even a logging or cleanup failure must not suppress the user's action.
        status = subprocess.call(["hyprctl", "dispatch", "exit"])
    return status


if __name__ == "__main__":
    raise SystemExit(main())
