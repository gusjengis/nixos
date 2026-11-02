"""Run over SSH stdin. Return credentials only through the encrypted channel."""
import fcntl
import json
import os
import pwd
from pathlib import Path
import secrets
import socket
import subprocess
import time


def readn(sock, length):
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise RuntimeError("RustDesk settings connection closed")
        data += chunk
    return data


def request(message):
    payload = json.dumps(message, separators=(",", ":")).encode()
    length = len(payload)
    size = 1 if length <= 63 else 2 if length <= 16383 else 3
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(5)
        sock.connect(f"/tmp/RustDesk-{os.getuid()}/ipc")
        sock.sendall(((length << 2) | (size - 1)).to_bytes(size, "little") + payload)
        head = readn(sock, 1)
        size = (head[0] & 3) + 1
        length = int.from_bytes(head + readn(sock, size - 1), "little") >> 2
        if length > 1024 * 1024:
            raise RuntimeError("Invalid RustDesk settings reply")
        return json.loads(readn(sock, length))


def provision():
    app = Path("/Applications/RustDesk.app")
    if not app.is_dir():
        subprocess.run(["/opt/homebrew/bin/brew", "install", "--cask", "rustdesk"],
                       stdout=subprocess.DEVNULL, check=True, timeout=300)
    ipc = Path(f"/tmp/RustDesk-{os.getuid()}/ipc")
    if not ipc.exists():
        subprocess.run(["/usr/bin/open", "-gj", str(app)], check=True)
    for _ in range(100):
        try:
            request({"t": "Config", "c": ["salt", None]})
            break
        except (OSError, RuntimeError):
            time.sleep(0.2)
    else:
        raise RuntimeError("Mac RustDesk service did not start")

    directory = Path.home() / ".local/share/macbook-remote"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (directory / "rustdesk-settings.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        secret = directory / "rustdesk-password"
        try:
            fd = os.open(secret, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as stream:
                stream.write(secrets.token_urlsafe(32) + "\n")
        fd = os.open(secret, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as stream:
            if os.fstat(stream.fileno()).st_mode & 0o077:
                raise RuntimeError("Mac RustDesk password must be private (0600)")
            password = stream.read().strip()
        if not password:
            raise RuntimeError("Mac RustDesk password file is empty")
        reply = request({"t": "Config", "c": ["permanent-password", password]})
        if reply.get("c") != ["permanent-password", "Y"]:
            raise RuntimeError("Mac RustDesk rejected unattended password setup")
        options = request({"t": "Options", "c": None})["c"]
        options.update({"direct-server": "Y", "approve-mode": "password",
                        "verification-method": "use-permanent-password",
                        "enable-hwcodec": "Y", "whitelist": "100.64.0.0/10"})
        request({"t": "Options", "c": options})
        salt = request({"t": "Config", "c": ["salt", None]})["c"][1]
        if not salt:
            raise RuntimeError("Mac RustDesk returned an empty authentication salt")
        return {"password": password, "salt": salt, "hostname": socket.gethostname(),
                "username": pwd.getpwuid(os.getuid()).pw_name, "platform": "Mac OS"}


if __name__ == "__main__":
    print(json.dumps(provision()))
