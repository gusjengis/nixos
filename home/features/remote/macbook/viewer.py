#!/usr/bin/env python3
"""Mac desktop over SSH; native Mac resolution follows the GTK viewport."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import shlex
import signal

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkVnc", "2.0")
from gi.repository import Gdk, GLib, Gtk, GtkVnc

ROOT = Path(__file__).resolve().parent
GLib.set_prgname("macbook-remote")
SECRET = Path.home() / ".config/secrets/logins/macos"
SSH = ["ssh", "-T", "-oBatchMode=yes", "-oConnectTimeout=10",
       "-oServerAliveInterval=10", "-oServerAliveCountMax=3"]


def setup_power(password=None):
    policy = (ROOT / "power-policy.sh").read_text()
    digest = hashlib.sha256(policy.encode()).hexdigest()[:16]
    directory = "/Library/Application Support/MacBookRemote"
    marker = f"{directory}/power-policy-{digest}"
    check = subprocess.run(SSH + ["macos", f"test -f {shlex.quote(marker)}"], timeout=20)
    if check.returncode == 0:
        return
    if password is None:
        _, password = credentials(None)
    label = "net.gusjengis.macbook-remote-power"
    plist = f"/Library/LaunchDaemons/{label}.plist"
    script = f'''set -eu
/bin/mkdir -p '{directory}'
/usr/sbin/chown root:wheel '{directory}'
/bin/chmod 755 '{directory}'
/bin/cat > '{directory}/power-policy.sh' <<'MACBOOK_POLICY'
{policy}
MACBOOK_POLICY
/usr/sbin/chown root:wheel '{directory}/power-policy.sh'
/bin/chmod 755 '{directory}/power-policy.sh'
/bin/cat > '{plist}' <<'MACBOOK_PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array><string>/bin/sh</string><string>{directory}/power-policy.sh</string></array>
<key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
<key>ThrottleInterval</key><integer>5</integer>
</dict></plist>
MACBOOK_PLIST
/usr/sbin/chown root:wheel '{plist}'
/bin/chmod 644 '{plist}'
/bin/launchctl bootout system/{label} 2>/dev/null || true
/bin/launchctl bootstrap system '{plist}'
/usr/bin/touch '{marker}'
'''
    result = subprocess.run(SSH + ["macos", "/usr/bin/sudo -S -p '' /bin/sh -s"],
                            input=password + "\n" + script, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("Could not configure Mac closed-lid power policy: " + result.stderr)


def credentials(parent):
    if SECRET.is_file():
        values = dict(line.split("=", 1) for line in SECRET.read_text().splitlines() if "=" in line)
        if values.get("password"):
            return values.get("username", "anthonygreen"), values["password"]
    dialog = Gtk.Dialog(title="MacBook — one-time setup", transient_for=parent, modal=True)
    dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save and connect", Gtk.ResponseType.OK)
    box = dialog.get_content_area()
    box.set_spacing(12)
    box.set_border_width(20)
    box.add(Gtk.Label(label="Mac login password for anthonygreen.\nSaved privately on this computer for automatic connections."))
    entry = Gtk.Entry(visibility=False, activates_default=True)
    box.add(entry)
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.show_all()
    response = dialog.run()
    password = entry.get_text()
    dialog.destroy()
    if response != Gtk.ResponseType.OK or not password:
        raise RuntimeError("Setup cancelled")
    SECRET.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(SECRET, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(f"username=anthonygreen\npassword={password}\n")
    return "anthonygreen", password


class Viewer:
    def __init__(self):
        self.session = None
        self.closed = False
        self.ready = False
        self.resize_timer = 0
        self.last_size = None
        self.error_shown = False
        self.window = Gtk.Window(title="MacBook — connecting…")
        self.window.set_default_size(1280, 800)
        self.window.connect("destroy", self.close)
        self.window.connect("key-press-event", self.key)
        self.display = GtkVnc.Display.new()
        self.display.set_scaling(True)
        self.display.set_force_size(False)
        self.display.set_shared_flag(True)
        # Apple sometimes supplies an empty cursor. Do not hide the local
        # pointer while waiting for a server-provided shape.
        self.display.set_pointer_local(True)
        self.display.set_pointer_force_visible(True)
        self.display.set_smoothing(False)
        self.display.set_lossy_encoding(True)
        self.display.connect("vnc-auth-credential", self.authenticate)
        self.display.connect("vnc-auth-failure", lambda _, message: self.fail(f"Mac authentication failed: {message}"))
        self.display.connect("vnc-error", lambda _, message: self.fail(message))
        self.display.connect("vnc-disconnected", lambda _: self.close())
        self.display.connect("vnc-initialized", self.initialized)
        self.display.connect("vnc-desktop-resize", self.desktop_resized)
        self.display.connect("size-allocate", self.size_changed)
        self.display.connect("vnc-server-cut-text", self.clipboard_from_mac)
        self.window.add(self.display)
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.remote_clipboard = None
        self.clipboard.connect("owner-change", self.clipboard_changed)
        self.window.show_all()
        self.username, self.password = credentials(self.window)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.close)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.close)
        threading.Thread(target=self.connect, daemon=True).start()
        GLib.timeout_add_seconds(10, self.heartbeat)

    def authenticate(self, display, requested):
        for index in range(requested.n_values):
            credential = requested.get_nth(index)
            value = {
                GtkVnc.DisplayCredential.USERNAME: self.username,
                GtkVnc.DisplayCredential.PASSWORD: self.password,
                GtkVnc.DisplayCredential.CLIENTNAME: "MacBook Remote",
            }.get(credential)
            if value is None:
                self.fail("Mac requested an unsupported authentication method")
                return
            display.set_credential(credential, value)

    def connect(self):
        try:
            setup_power(self.password)
            source = (ROOT / "display-session.swift").read_bytes()
            digest = hashlib.sha256(source).hexdigest()[:16]
            helper = f'"$HOME/.local/share/macbook-remote/display-session-{digest}"'
            command = (f'umask 077; mkdir -p "$HOME/.local/share/macbook-remote"; '
                       f'test -x {helper} || /usr/bin/swiftc - -o {helper}')
            result = subprocess.run(SSH + ["macos", command], input=source, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError(result.stderr.decode(errors="replace"))
            self.session = subprocess.Popen(
                SSH + ["macos", helper],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
            threading.Thread(target=self.read_errors, daemon=True).start()
            for line in self.session.stdout:
                message = json.loads(line)
                if "error" in message:
                    raise RuntimeError(message["error"])
                if message.get("ready"):
                    GLib.idle_add(self.open_display)
                elif "width" in message:
                    GLib.idle_add(self.window.set_title, f'MacBook — {message["width"]}×{message["height"]}')
            if not self.closed:
                raise RuntimeError("Mac display session ended")
        except Exception as error:
            GLib.idle_add(self.fail, str(error))

    def read_errors(self):
        for line in self.session.stderr:
            print("MacBook:", line.rstrip(), flush=True)

    def open_display(self):
        if not self.closed:
            # Tailscale encrypts the VNC stream end-to-end. Keep display-control
            # SSH separate so video cannot queue behind an SSH forwarding hop.
            self.display.open_host("macos.tail29bd65.ts.net", "5900")
        return False

    def initialized(self, _):
        print("MacBook: authenticated VNC desktop initialized", flush=True)
        self.ready = True
        self.display.grab_focus()
        self.size_changed(self.display, self.display.get_allocation())

    def desktop_resized(self, _, width, height):
        print(f"MacBook: VNC framebuffer {width}x{height}", flush=True)

    def size_changed(self, _, allocation):
        if self.ready and allocation.width >= 320 and allocation.height >= 200:
            if self.resize_timer:
                GLib.source_remove(self.resize_timer)
            self.resize_timer = GLib.timeout_add(400, self.resize)

    def resize(self):
        self.resize_timer = 0
        size = (self.display.get_allocated_width(), self.display.get_allocated_height())
        if size != self.last_size:
            self.send(f"{size[0]} {size[1]}")
            self.last_size = size
        return False

    def send(self, line):
        if self.session and self.session.poll() is None and not self.closed:
            try:
                self.session.stdin.write(line + "\n")
                self.session.stdin.flush()
            except (BrokenPipeError, ValueError):
                self.fail("Mac connection lost")

    def heartbeat(self):
        self.send("ping")
        return not self.closed

    def key(self, _, event):
        if event.keyval == Gdk.KEY_F11:
            if self.window.get_window().get_state() & Gdk.WindowState.FULLSCREEN:
                self.window.unfullscreen()
            else:
                self.window.fullscreen()
            return True
        return False

    def clipboard_from_mac(self, _, text):
        self.remote_clipboard = text
        self.clipboard.set_text(text, -1)

    def clipboard_changed(self, clipboard, _):
        clipboard.request_text(self.clipboard_text, None)

    def clipboard_text(self, _, text, _data):
        if self.ready and text is not None and text != self.remote_clipboard:
            self.display.client_cut_text(text)

    def fail(self, message):
        if self.closed or self.error_shown:
            return False
        self.error_shown = True
        dialog = Gtk.MessageDialog(transient_for=self.window, modal=True,
                                   message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                                   text="MacBook connection failed")
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()
        self.close()
        return False

    def close(self, *_):
        if self.closed:
            return
        self.closed = True
        if self.session:
            try:
                self.session.stdin.close()
                self.session.wait(timeout=15)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.session.terminate()
        self.window.hide()
        Gtk.main_quit()


if __name__ == "__main__":
    try:
        viewer = Viewer()
        Gtk.main()
    except Exception as error:
        subprocess.run(["notify-send", "MacBook", str(error)], check=False)
        raise SystemExit(1)
