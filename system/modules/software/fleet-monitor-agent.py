#!/usr/bin/env python3
import json
import os
import pathlib
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import psutil


CONFIG = json.loads(os.environ["FLEET_MONITOR_CONFIG"])
STATE_DIR = pathlib.Path(os.environ.get("STATE_DIRECTORY", "/var/lib/fleet-monitor-agent"))
HISTORY = STATE_DIR / "health.jsonl"
LOCK = threading.Lock()
LATEST = {}
PREVIOUS_NET = None
PREVIOUS_AT = None


def command(args, timeout=8):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
        # Several diagnostic tools return non-zero when they successfully
        # report a degraded state; their output is the data we need most.
        return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def json_command(args, timeout=10):
    output = command(args, timeout)
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"raw": output}


def tailscale_login(address):
    if address in ("127.0.0.1", "::1"):
        return CONFIG["owner_login"]
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(3)
    try:
        client.connect("/run/tailscale/tailscaled.sock")
        target = quote(f"{address}:1", safe="")
        request = f"GET /localapi/v0/whois?addr={target} HTTP/1.1\r\nHost: local-tailscaled.sock\r\nConnection: close\r\n\r\n"
        client.sendall(request.encode())
        response = b""
        while chunk := client.recv(65536):
            response += chunk
        header, body = response.split(b"\r\n\r\n", 1)
        if b" 200 " not in header.split(b"\r\n", 1)[0]:
            return None
        return json.loads(body).get("UserProfile", {}).get("LoginName")
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    finally:
        client.close()


def trim(value, limit=4000):
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "..."
    if isinstance(value, dict):
        return {key: trim(item, limit) for key, item in value.items()}
    if isinstance(value, list):
        return [trim(item, limit) for item in value]
    return value


def collect_tmux():
    fmt = "#{session_name}\t#{window_index}\t#{window_name}\t#{pane_current_command}\t#{pane_current_path}\t#{window_active}"
    output = command(["runuser", "-u", CONFIG["user"], "--", "tmux", "list-windows", "-a", "-F", fmt])
    sessions = {}
    for line in output.splitlines():
        fields = line.split("\t", 5)
        if len(fields) != 6:
            continue
        session, index, name, program, path, active = fields
        sessions.setdefault(session, []).append(
            {"index": index, "name": name, "program": program, "path": path, "active": active == "1"}
        )
    return [{"name": name, "windows": windows} for name, windows in sorted(sessions.items())]


def collect_services():
    running = command(
        ["systemctl", "list-units", "--type=service", "--state=running", "--no-legend", "--plain"]
    )
    running_names = [line.split()[0] for line in running.splitlines() if line.split()]
    failed = command(["systemctl", "--failed", "--type=service", "--no-legend", "--plain"])
    failed_names = [line.split()[0] for line in failed.splitlines() if line.split()]
    declared = []
    for service in CONFIG.get("services", []):
        unit = service["unit"]
        state = command(["systemctl", "is-active", unit]) or "unknown"
        declared.append({**service, "state": state})
    return {"declared": declared, "running": running_names, "failed": failed_names}


def collect_processes():
    processes = []
    for process in psutil.process_iter(["pid", "username", "name", "cmdline", "cpu_percent", "memory_percent"]):
        try:
            info = process.info
            processes.append(
                {
                    "pid": info["pid"],
                    "user": info["username"] or "",
                    "name": info["name"] or "",
                    "command": " ".join(info["cmdline"] or [])[:300],
                    "cpu": round(info["cpu_percent"] or 0, 1),
                    "memory": round(info["memory_percent"] or 0, 1),
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
    return sorted(processes, key=lambda item: (item["cpu"] + item["memory"]), reverse=True)[:75]


def collect_storage():
    drives = []
    seen = set()
    for partition in psutil.disk_partitions(all=False):
        if partition.mountpoint in seen:
            continue
        seen.add(partition.mountpoint)
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (OSError, PermissionError):
            continue
        drives.append(
            {
                "device": partition.device,
                "mount": partition.mountpoint,
                "filesystem": partition.fstype,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
                "percent": usage.percent,
            }
        )
    return drives


def collect_smart():
    scan = json_command(["smartctl", "--scan-open", "-j"]) or {}
    results = []
    for device in scan.get("devices", []):
        name = device.get("name")
        if not name:
            continue
        data = json_command(["smartctl", "-n", "standby", "-a", "-j", name], timeout=20)
        if data:
            results.append(trim(data))
    return results


def collect_hardware():
    temperatures = {}
    try:
        for group, entries in psutil.sensors_temperatures().items():
            temperatures[group] = [
                {"label": item.label, "current": item.current, "high": item.high, "critical": item.critical}
                for item in entries
            ]
    except (AttributeError, OSError):
        pass
    fans = {}
    try:
        fans = {
            group: [{"label": item.label, "rpm": item.current} for item in entries]
            for group, entries in psutil.sensors_fans().items()
        }
    except (AttributeError, OSError):
        pass
    battery = None
    try:
        item = psutil.sensors_battery()
        if item:
            battery = {"percent": item.percent, "plugged": item.power_plugged, "seconds_left": item.secsleft}
    except (AttributeError, OSError):
        pass
    return {
        "temperatures": temperatures,
        "fans": fans,
        "battery": battery,
        "smart": collect_smart(),
        "nvme": json_command(["nvme", "list", "-o", "json"]) or {},
        "sensors_raw": json_command(["sensors", "-j"]) or {},
        "pci": command(["lspci", "-mm"]),
        "usb": command(["lsusb"]),
    }


def collect_network(now):
    global PREVIOUS_NET, PREVIOUS_AT
    counters = psutil.net_io_counters(pernic=True)
    interfaces = {}
    elapsed = now - PREVIOUS_AT if PREVIOUS_AT else 0
    for name, counter in counters.items():
        previous = PREVIOUS_NET.get(name) if PREVIOUS_NET else None
        interfaces[name] = {
            "rx_bytes": counter.bytes_recv,
            "tx_bytes": counter.bytes_sent,
            "rx_per_second": round((counter.bytes_recv - previous.bytes_recv) / elapsed) if previous and elapsed > 0 else 0,
            "tx_per_second": round((counter.bytes_sent - previous.bytes_sent) / elapsed) if previous and elapsed > 0 else 0,
        }
    PREVIOUS_NET = counters
    PREVIOUS_AT = now
    tailscale = json_command(["tailscale", "status", "--json"]) or {}
    own = tailscale.get("Self", {})
    return {
        "interfaces": interfaces,
        "tailscale": {
            "online": own.get("Online", False),
            "ips": own.get("TailscaleIPs", []),
            "dns_name": own.get("DNSName", "").rstrip("."),
            "health": tailscale.get("Health", []),
        },
    }


def health_concerns(snapshot):
    concerns = []
    for drive in snapshot["storage"]:
        if drive["percent"] >= 90:
            concerns.append({"severity": "critical", "source": drive["mount"], "message": f"Filesystem {drive['percent']}% full"})
        elif drive["percent"] >= 80:
            concerns.append({"severity": "warning", "source": drive["mount"], "message": f"Filesystem {drive['percent']}% full"})
    for group, entries in snapshot["hardware"]["temperatures"].items():
        for item in entries:
            threshold = item["critical"] or item["high"] or 90
            if item["current"] and item["current"] >= threshold:
                concerns.append({"severity": "critical", "source": group, "message": f"{item['label'] or 'sensor'} is {item['current']} C"})
    for disk in snapshot["hardware"]["smart"]:
        passed = disk.get("smart_status", {}).get("passed")
        if passed is False:
            name = disk.get("device", {}).get("name", "disk")
            concerns.append({"severity": "critical", "source": name, "message": "SMART health check failed"})
    for unit in snapshot["services"]["failed"]:
        concerns.append({"severity": "warning", "source": unit, "message": "Systemd service failed"})
    for problem in snapshot["network"]["tailscale"]["health"]:
        concerns.append({"severity": "warning", "source": "tailscale", "message": str(problem)})
    return concerns


def collect():
    now = time.time()
    load = psutil.getloadavg()
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    snapshot = {
        "schema": 1,
        "host": CONFIG["host"],
        "description": CONFIG["description"],
        "collected_at": now,
        "boot_time": psutil.boot_time(),
        "system": {
            "cpu_percent": psutil.cpu_percent(interval=0.2),
            "cpu_count": psutil.cpu_count(),
            "load": load,
            "memory": {"total": memory.total, "used": memory.used, "available": memory.available, "percent": memory.percent},
            "swap": {"total": swap.total, "used": swap.used, "percent": swap.percent},
            "kernel": command(["uname", "-r"]),
            "generation": os.path.realpath("/run/current-system").rsplit("/", 1)[-1],
        },
        "network": collect_network(now),
        "storage": collect_storage(),
        "hardware": collect_hardware(),
        "services": collect_services(),
        "tmux": collect_tmux(),
        "processes": collect_processes(),
        "recent_errors": command(["journalctl", "-p", "0..3", "--since", "-24 hours", "--no-pager", "-n", "80"]),
    }
    snapshot["concerns"] = health_concerns(snapshot)
    return snapshot


def store(snapshot):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, separators=(",", ":")) + "\n")
    if HISTORY.stat().st_size > CONFIG.get("max_history_bytes", 25_000_000):
        lines = HISTORY.read_text(encoding="utf-8").splitlines()[-500:]
        HISTORY.write_text("\n".join(lines) + "\n", encoding="utf-8")


def collector_loop():
    global LATEST
    while True:
        try:
            snapshot = collect()
            with LOCK:
                LATEST = snapshot
            store(snapshot)
        except Exception as error:
            with LOCK:
                if LATEST:
                    LATEST = {**LATEST, "collector_error": str(error), "collector_error_at": time.time()}
                else:
                    LATEST = {"host": CONFIG["host"], "collected_at": time.time(), "collector_error": str(error)}
        time.sleep(CONFIG.get("interval", 300))


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if tailscale_login(self.client_address[0]) != CONFIG["owner_login"]:
            self.send_json({"error": "forbidden"}, 403)
            return
        parsed = urlparse(self.path)
        if parsed.path == "/snapshot":
            with LOCK:
                self.send_json(LATEST)
            return
        if parsed.path == "/history":
            try:
                limit = max(1, min(int(parse_qs(parsed.query).get("limit", ["24"])[0]), 500))
            except ValueError:
                limit = 24
            try:
                lines = HISTORY.read_text(encoding="utf-8").splitlines()[-limit:]
                self.send_json([json.loads(line) for line in lines])
            except (OSError, json.JSONDecodeError):
                self.send_json([])
            return
        self.send_json({"error": "not found"}, 404)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=collector_loop, daemon=True).start()
    ThreadingHTTPServer((CONFIG.get("listen", "0.0.0.0"), CONFIG["port"]), Handler).serve_forever()
