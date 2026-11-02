#!/usr/bin/env python3
"""Own a Mac display session while RustDesk handles native video and input."""
import hashlib
import json
import os
from pathlib import Path
import queue
import signal
import socket
import subprocess
import tempfile
import threading
import time
import tomllib

import tomli_w

from viewer import ROOT, SSH, setup_power


def provision_peer(ip):
    result = subprocess.run(SSH + ["macos", "/usr/bin/python3 -"],
                            input=(ROOT / "rustdesk-host.py").read_bytes(),
                            capture_output=True, timeout=360)
    if result.returncode:
        raise RuntimeError("Mac RustDesk setup failed: " + result.stderr.decode(errors="replace"))
    host = json.loads(result.stdout)
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    directory = config_home / "rustdesk/peers"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    peer = directory / f"{ip}.toml"
    data = tomllib.loads(peer.read_text()) if peer.exists() else {}
    data["password"] = list(hashlib.sha256((host["password"] + host["salt"]).encode()).digest())
    data.update(view_style="adaptive", image_quality="custom", custom_image_quality=[80],
                show_remote_cursor=True, show_quality_monitor=False)
    data.setdefault("options", {}).update({"custom-fps": "60", "codec-preference": "h265",
                                           "i444": "N", "collapse_toolbar": "Y",
                                           "hide-toolbar": "Y"})
    # RustDesk's recent-peer scan deletes files with empty platform metadata.
    # Seed this before the GUI starts, otherwise unattended login is discarded.
    data["info"] = {key: host[key] for key in ("username", "hostname", "platform")}
    # RustDesk only hides its tab strip in its own fullscreen UI state. Hyprland
    # keeps that client state while retaining an ordinary tiled/floating window.
    ui = data.setdefault("ui_flutter", {})
    frame = json.loads(ui.get("wm_RemoteDesktop", "{}"))
    frame.update(isFullscreen=True, isMaximized=False)
    ui["wm_RemoteDesktop"] = json.dumps(frame)
    fd, temporary = tempfile.mkstemp(prefix=".macbook-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            tomli_w.dump(data, stream)
        os.replace(temporary, peer)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def clients():
    result = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True,
                            timeout=5, check=True)
    return json.loads(result.stdout)


def remote_window(ip):
    return next((window for window in clients()
                 if window.get("class", "").lower() == "rustdesk"
                 and ip in window.get("initialTitle", "")
                 and "Remote Desktop" in window.get("initialTitle", "")), None)


def viewport(window, monitors):
    scale = next((item["scale"] for item in monitors if item["id"] == window["monitor"]), 1)
    width, height = window["size"]
    # Hardware video encoders require even dimensions.
    return tuple(max(minimum, min(maximum, int(value * scale) // 2 * 2))
                 for value, minimum, maximum in ((width, 320, 7680), (height, 200, 4320)))


class DisplaySession:
    def __init__(self):
        self.process = None
        self.messages = queue.Queue()
        self.stopped = threading.Event()

    def start(self):
        source = (ROOT / "display-session.swift").read_bytes()
        digest = hashlib.sha256(source).hexdigest()[:16]
        helper = f'"$HOME/.local/share/macbook-remote/display-session-{digest}"'
        command = (f'umask 077; mkdir -p "$HOME/.local/share/macbook-remote"; '
                   f'test -x {helper} || /usr/bin/swiftc - -o {helper}')
        result = subprocess.run(SSH + ["macos", command], input=source,
                                capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))
        self.process = subprocess.Popen(SSH + ["macos", helper], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, text=True, bufsize=1)
        threading.Thread(target=self.read, daemon=True).start()
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline and not self.stopped.is_set():
            try:
                message = self.messages.get(timeout=0.2)
            except queue.Empty:
                if self.process.poll() is not None:
                    raise RuntimeError("Mac display helper exited before becoming ready")
                continue
            if "error" in message:
                raise RuntimeError(message["error"])
            if message.get("ready"):
                return
        raise RuntimeError("Mac display setup interrupted or timed out")

    def read(self):
        try:
            for line in self.process.stdout:
                self.messages.put(json.loads(line))
        except (ValueError, OSError):
            self.messages.put({"error": "Invalid reply from Mac display helper"})

    def send(self, text):
        if self.process.poll() is not None:
            raise RuntimeError("Mac display connection ended")
        self.process.stdin.write(text + "\n")
        self.process.stdin.flush()

    def close(self):
        if self.process:
            try:
                self.process.stdin.close()
            except BrokenPipeError:
                pass
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)


def main():
    ip = socket.gethostbyname("macos.tail29bd65.ts.net")
    existing = remote_window(ip)
    if existing:
        subprocess.run(["hyprctl", "dispatch",
                        f'hl.dsp.focus({{window="address:{existing["address"]}"}})'], check=True)
        return
    session = DisplaySession()
    process = None
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, lambda *_: session.stopped.set())
    try:
        setup_power()
        session.start()
        provision_peer(ip)
        if session.stopped.is_set():
            return
        # Password is seeded privately; argv and application logs contain no secret.
        process = subprocess.Popen(["rustdesk", "--connect", ip])
        deadline = time.monotonic() + 45
        seen = False
        borderless = False
        candidate = None
        settled = 0
        applied = None
        heartbeat = 0
        monitors = json.loads(subprocess.check_output(["hyprctl", "-j", "monitors"], timeout=5))
        while not session.stopped.wait(0.25):
            now = time.monotonic()
            if now - heartbeat >= 5:
                session.send("ping")
                heartbeat = now
            while not session.messages.empty():
                message = session.messages.get_nowait()
                if "error" in message:
                    raise RuntimeError(message["error"])
            window = remote_window(ip)
            if window:
                seen = True
                if not borderless and window.get("fullscreenClient") == 2:
                    address = "address:" + window["address"]
                    subprocess.run(["hyprctl", "dispatch",
                                    'hl.dsp.window.fullscreen_state({internal=0,client=2,'
                                    f'action="set",window="{address}"}})'],
                                   check=True, capture_output=True)
                    borderless = True
                    # The fullscreen request's dimensions precede the new tiled size.
                    continue
                size = viewport(window, monitors)
                if size != candidate:
                    candidate, settled = size, now
                elif size != applied and now - settled >= 0.5:
                    session.send(f"{size[0]} {size[1]}")
                    applied = size
            elif seen:
                break
            elif now >= deadline:
                raise RuntimeError("RustDesk remote window did not open")
            elif process.poll() not in (None, 0):
                raise RuntimeError("RustDesk could not start")
    finally:
        try:
            if process is not None:
                window = remote_window(ip)
                if window:
                    subprocess.run(["hyprctl", "dispatch",
                                    f'hl.dsp.window.close({{window="address:{window["address"]}"}})'],
                                   capture_output=True, timeout=5, check=False)
        finally:
            session.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        subprocess.run(["notify-send", "MacBook connection failed", str(error)], check=False)
        raise SystemExit(1)
