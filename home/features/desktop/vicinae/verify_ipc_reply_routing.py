"""Live regression check: independent CLI clients all begin with request id 1."""
from concurrent.futures import ThreadPoolExecutor
import subprocess
import time


def menu():
    process = subprocess.Popen(
        ["vicinae", "dmenu", "--no-section", "--no-footer", "--no-quick-look",
         "--placeholder", "Launcher reliability check…", "--width", "640", "--height", "142"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    process.stdin.write("Reply routing test\n")
    process.stdin.close()
    time.sleep(0.15)
    if process.poll() is not None:
        raise AssertionError("Picker exited before its reply was requested: " + process.stderr.read())
    return process


def query(_):
    result = subprocess.run(["vicinae", "state", "open"], capture_output=True, timeout=2)
    assert result.returncode == 0, result.stderr


if __name__ == "__main__":
    for _ in range(50):
        try:
            ready = subprocess.run(["vicinae", "state", "open"], capture_output=True, timeout=0.5)
            if ready.returncode in (0, 1) and not ready.stderr:
                break
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.1)
    else:
        raise RuntimeError("Vicinae server did not become ready")
    menus = []
    try:
        for cycle in range(5):
            current = menu()
            menus.append(current)
            with ThreadPoolExecutor(max_workers=5) as pool:
                list(pool.map(query, range(20)))
            assert current.poll() is None, "State query stole the pending picker reply"
            replacement = menu()
            menus.append(replacement)
            current.wait(timeout=2)
            assert replacement.poll() is None, "Replacement picker lost its reply target"
            query(None)
            subprocess.run(["vicinae", "close"], capture_output=True, timeout=2, check=True)
            replacement.wait(timeout=2)
        print("PASS: 100 concurrent state queries, 5 picker replacements, 5 closes; no stolen replies or hangs.")
    finally:
        for process in menus:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)
