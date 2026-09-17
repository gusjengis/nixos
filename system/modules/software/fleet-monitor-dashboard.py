#!/usr/bin/env python3
import concurrent.futures
import json
import os
import pathlib
import smtplib
import socket
import ssl
import subprocess
import threading
import time
import urllib.error
import urllib.request
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, urlparse


CONFIG = json.loads(os.environ["FLEET_MONITOR_CONFIG"])
STATE_DIR = pathlib.Path(os.environ.get("STATE_DIRECTORY", "/var/lib/fleet-monitor-dashboard"))
STATE_FILE = STATE_DIR / "state.json"
LOCK = threading.Lock()
STATE = {"hosts": {}, "updated_at": 0}
ALERTED = {}


def load_state():
    global STATE, ALERTED
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        STATE = saved.get("state", STATE)
        ALERTED = saved.get("alerted", {})
    except (OSError, json.JSONDecodeError):
        pass


def save_state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"state": STATE, "alerted": ALERTED}), encoding="utf-8")
    temporary.replace(STATE_FILE)


def fetch_json(url, timeout=12):
    request = urllib.request.Request(url, headers={"User-Agent": "fleet-monitor/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


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


def ping(host):
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["tailscale", "ping", "--timeout=3s", "--c=1", host],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return round((time.monotonic() - started) * 1000) if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def poll_host(host):
    name = host["name"]
    started = time.monotonic()
    try:
        snapshot = fetch_json(f"http://{host['address']}:{CONFIG['agent_port']}/snapshot")
        latency = round((time.monotonic() - started) * 1000)
        if not snapshot:
            raise RuntimeError("empty collector response")
        if snapshot.get("collector_error"):
            snapshot.setdefault("concerns", []).append(
                {"severity": "warning", "source": "collector", "message": snapshot["collector_error"]}
            )
        return name, {
            "online": True,
            "latency_ms": latency,
            "checked_at": time.time(),
            "inventory": host,
            "snapshot": snapshot,
        }
    except Exception as error:
        return name, {
            "online": False,
            "latency_ms": ping(host["address"]),
            "checked_at": time.time(),
            "inventory": host,
            "error": str(error),
        }


def smtp_configured():
    return all(os.environ.get(key) for key in ("ALERT_SMTP_HOST", "ALERT_SMTP_FROM", "ALERT_EMAIL_TO"))


def send_email(subject, body):
    if not smtp_configured():
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["ALERT_SMTP_FROM"]
    message["To"] = os.environ["ALERT_EMAIL_TO"]
    message.set_content(body)
    host = os.environ["ALERT_SMTP_HOST"]
    port = int(os.environ.get("ALERT_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        if os.environ.get("ALERT_SMTP_STARTTLS", "true").lower() == "true":
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
        user = os.environ.get("ALERT_SMTP_USER")
        password = os.environ.get("ALERT_SMTP_PASSWORD")
        if user and password:
            smtp.login(user, password)
        smtp.send_message(message)
    return True


def alert_key(host, concern):
    return f"{host}:{concern['severity']}:{concern['source']}:{concern['message']}"


def process_alerts(results, previous_hosts):
    now = time.time()
    active = set()
    for name, status in results.items():
        concerns = status.get("snapshot", {}).get("concerns", []) if status["online"] else []
        if not status["online"]:
            previous = previous_hosts.get(name, {})
            if previous and not previous.get("online"):
                if status.get("latency_ms") is None:
                    concerns = [{"severity": "critical", "source": "reachability", "message": "Host unreachable for two checks"}]
                else:
                    concerns = [{"severity": "warning", "source": "monitor", "message": "Monitoring agent unreachable for two checks"}]
        for concern in concerns:
            key = alert_key(name, concern)
            active.add(key)
            if now - ALERTED.get(key, 0) < CONFIG["alert_repeat_seconds"]:
                continue
            body = (
                f"Machine: {name}\nSeverity: {concern['severity']}\nSource: {concern['source']}\n"
                f"Problem: {concern['message']}\nDashboard: http://alpha:{CONFIG['port']}\n"
            )
            try:
                if send_email(f"[fleet] {name}: {concern['message']}", body):
                    ALERTED[key] = now
            except Exception as error:
                print(f"email alert failed: {error}", flush=True)
    for key in list(ALERTED):
        if key not in active and now - ALERTED[key] > CONFIG["alert_repeat_seconds"]:
            del ALERTED[key]


def ai_configured():
    return bool(os.environ.get("AI_API_KEY") and os.environ.get("AI_MODEL"))


def summarize_hardware(name, status, previous_summary):
    if not ai_configured() or not status.get("online"):
        return previous_summary
    if previous_summary and time.time() - previous_summary.get("generated_at", 0) < CONFIG["summary_interval_seconds"]:
        return previous_summary
    snapshot = status["snapshot"]
    health = {
        "host": name,
        "description": snapshot.get("description"),
        "uptime_seconds": time.time() - snapshot.get("boot_time", time.time()),
        "storage": snapshot.get("storage"),
        "temperatures": snapshot.get("hardware", {}).get("temperatures"),
        "fans": snapshot.get("hardware", {}).get("fans"),
        "battery": snapshot.get("hardware", {}).get("battery"),
        "smart": snapshot.get("hardware", {}).get("smart"),
        "failed_services": snapshot.get("services", {}).get("failed"),
        "recent_concerns": snapshot.get("concerns"),
    }
    prompt = (
        "You are a cautious Linux hardware health analyst. Interpret this telemetry in 3-6 concise sentences. "
        "Lead with risk level (healthy, watch, or urgent), cite concrete evidence, distinguish missing telemetry "
        "from healthy telemetry, and recommend only necessary action. Do not infer facts absent from data.\n\n"
        + json.dumps(health, separators=(",", ":"))
    )
    payload = {
        "model": os.environ["AI_MODEL"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 350,
    }
    endpoint = os.environ.get("AI_API_URL", "https://api.openai.com/v1/chat/completions")
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {os.environ['AI_API_KEY']}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            data = json.load(response)
        text = data["choices"][0]["message"]["content"].strip()
        return {"generated_at": time.time(), "text": text}
    except Exception as error:
        print(f"AI summary failed for {name}: {error}", flush=True)
        return {
            "generated_at": time.time(),
            "text": previous_summary.get("text", "") if previous_summary else "",
            "error": str(error),
        }


def poll_loop():
    global STATE
    while True:
        worker_count = max(1, min(len(CONFIG["hosts"]), 16))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            polled = dict(pool.map(poll_host, CONFIG["hosts"]))
        with LOCK:
            old_hosts = STATE.get("hosts", {}).copy()
        process_alerts(polled, old_hosts)
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as pool:
            summaries = pool.map(
                lambda item: (item[0], summarize_hardware(item[0], item[1], old_hosts.get(item[0], {}).get("ai_summary"))),
                polled.items(),
            )
            for name, summary in summaries:
                polled[name]["ai_summary"] = summary
        with LOCK:
            STATE = {"hosts": polled, "updated_at": time.time(), "smtp_configured": smtp_configured(), "ai_configured": ai_configured()}
            save_state()
        time.sleep(CONFIG["poll_interval"])


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if tailscale_login(self.client_address[0]) != CONFIG["owner_login"]:
            self.send_bytes(b'{"error":"forbidden"}', "application/json", 403)
            return
        path = urlparse(self.path).path
        if path == "/api/status":
            with LOCK:
                body = json.dumps(STATE).encode()
            self.send_bytes(body, "application/json")
            return
        if path in ("/", "/index.html"):
            self.send_bytes(pathlib.Path(CONFIG["ui_file"]).read_bytes(), "text/html; charset=utf-8")
            return
        self.send_bytes(b'{"error":"not found"}', "application/json", 404)

    def log_message(self, *_args):
        pass


if __name__ == "__main__":
    load_state()
    threading.Thread(target=poll_loop, daemon=True).start()
    ThreadingHTTPServer((CONFIG.get("listen", "0.0.0.0"), CONFIG["port"]), Handler).serve_forever()
