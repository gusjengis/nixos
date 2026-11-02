"""Live acceptance check; briefly switches workspaces and restarts Vicinae.

Uses the installed package, its real app activation IPC and real Kitty windows.
Restores the original workspace/server and removes all probe windows/files.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def wait_for(fn, timeout=25):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for probe")


def clients():
    return json.loads(run("hyprctl", "-j", "clients"))


def dispatch(expr):
    assert run("hyprctl", "dispatch", expr) == "ok"


def focus(workspace):
    assert run("hyprctl", "eval", "hl.get_active_monitor():set_special_workspace(nil); hl.get_active_monitor():set_workspace("
               + json.dumps(workspace) + ")") == "ok"


def restart_server():
    subprocess.Popen(["vicinae-with-glass", "server", "--replace"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    time.sleep(3)
    run("vicinae", "ping")


def probe(directory, delay, *extra):
    directory = Path(directory)
    (directory / "metadata.json").write_text(json.dumps({
        "cwd": os.getcwd(), "args": list(extra),
        "token": os.environ.get("HL_INITIAL_WORKSPACE_TOKEN"),
    }))
    time.sleep(float(delay))
    name = directory.name
    os.execvp("kitty", ["kitty", "--class", name, "-e", sys.executable,
                        __file__, "--parent", str(directory)])


def parent(directory):
    directory = Path(directory)
    wait_for(lambda: (directory / "spawn-child").exists(), timeout=60)
    subprocess.Popen(["kitty", "--class", directory.name + "-child", "-e", "sleep", "60"])
    time.sleep(60)


def main():
    suffix = uuid.uuid4().hex[:8]
    app_id = "opencode-workspace-probe-" + suffix
    desktop = Path.home() / ".local/share/applications" / (app_id + ".desktop")
    assert not desktop.exists()
    origin = json.loads(run("hyprctl", "-j", "activeworkspace"))["name"]
    monitor = next(m for m in json.loads(run("hyprctl", "-j", "monitors")) if m["focused"])
    origin_special = monitor["specialWorkspace"]["name"]
    names = ["tracking-" + suffix + "-" + x for x in "abc"]
    with tempfile.TemporaryDirectory(prefix="workspace-tracking-", dir="/tmp/opencode") as tmp:
        root = Path(tmp)
        cwd = root / "working ' directory ]=]"
        cwd.mkdir()
        first = root / ("tracking-probe-" + suffix)
        second = root / ("tracking-probe-second-" + suffix)
        first.mkdir()
        second.mkdir()
        extras = ["spaces and 'quotes'", "$(touch SHOULD_NOT_EXIST)", "]]; ]=]", "Unicode: café 雪", "line\nbreak"]
        desktop.write_text("[Desktop Entry]\nType=Application\nName=Workspace tracking probe\n"
                           + "Exec=" + sys.executable + " " + str(Path(__file__).resolve())
                           + " --probe %U\nPath=" + str(cwd) + "\nTerminal=false\n")
        try:
            restart_server()
            subprocess.run(["vicinae", "close"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            focus(names[0])
            run("vicinae", "open")
            focus(names[1])
            # Same AppService::launch path as Enter. Launcher opened on A;
            # activation occurs on B; windows must remain on B after switching C.
            run("vicinae", "app", "launch", "--new", app_id, "--", str(first), "12", *extras)
            metadata = wait_for(lambda: (first / "metadata.json").exists())
            metadata = json.loads((first / "metadata.json").read_text())
            focus(names[2])
            subprocess.run(["vicinae", "close"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            assert metadata["cwd"] == str(cwd), metadata
            assert metadata["args"] == extras, metadata
            assert metadata["token"], metadata
            assert not (cwd / "SHOULD_NOT_EXIST").exists()
            window = wait_for(lambda: next((w for w in clients() if w["class"] == first.name), None))
            assert window["workspace"]["name"] == names[1], window
            assert json.loads(run("hyprctl", "-j", "activeworkspace"))["name"] == names[2]
            print("PASS: activation workspace B, not launcher-open A or mapping C; delay >10s; focus retained")
            print("PASS: arguments, Unicode, newlines, shell/Lua quoting and working directory")

            dispatch("hl.dsp.window.move({window=" + json.dumps("address:" + window["address"])
                     + ", workspace=" + json.dumps(names[0]) + ", follow=false})")
            (first / "spawn-child").touch()
            child = wait_for(lambda: next((w for w in clients() if w["class"] == first.name + "-child"), None))
            assert child["workspace"]["name"] == names[0], child
            assert json.loads(run("hyprctl", "-j", "activeworkspace"))["name"] == names[2]
            print("PASS: child follows moved parent on A while C remains focused")

            focus(names[2])
            run("vicinae", "app", "launch", "--new", app_id, "--", str(second), "0")
            wait_for(lambda: (second / "metadata.json").exists())
            other = json.loads((second / "metadata.json").read_text())
            assert other["token"] and other["token"] != metadata["token"]
            other_window = wait_for(lambda: next((w for w in clients() if w["class"] == second.name), None))
            assert other_window["workspace"]["name"] == names[2], other_window
            print("PASS: second activation gets fresh token and current workspace C")
        finally:
            subprocess.run(["vicinae", "close"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for window in clients():
                if window["class"].startswith((first.name, second.name)):
                    dispatch("hl.dsp.window.close({window=" + json.dumps("address:" + window["address"]) + "})")
            focus(origin)
            if origin_special:
                assert run("hyprctl", "eval", "hl.get_active_monitor():set_special_workspace("
                           + json.dumps(origin_special.removeprefix("special:")) + ")") == "ok"
            desktop.unlink(missing_ok=True)
            restart_server()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--probe":
        probe(*sys.argv[2:])
    elif len(sys.argv) > 1 and sys.argv[1] == "--parent":
        parent(sys.argv[2])
    else:
        main()
