"""Read private RDP rows at runtime; never expose passwords in argv or listings."""

import argparse
from collections import deque
import csv
import ipaddress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def read_remotes(path):
    with open(path, newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        required = {"name", "ip", "domain_user", "password"}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("CSV requires name, ip, domain_user, password columns")
        rows = []
        names = set()
        for line, row in enumerate(reader, 2):
            if not any(row.values()):
                continue
            if any(row.get(field) is None for field in required) or None in row:
                raise ValueError(f"Incorrect column count on CSV row {line}")
            for field in ("name", "ip", "domain_user"):
                row[field] = row[field].strip()
                if not row[field] or any(c in row[field] for c in "\r\n\t"):
                    raise ValueError(f"Invalid {field} on CSV row {line}")
            if any(c in row["password"] for c in "\r\n"):
                raise ValueError(f"Password must be one line on CSV row {line}")
            try:
                ipaddress.ip_address(row["ip"])
            except ValueError:
                raise ValueError(f"Invalid IP on CSV row {line}") from None
            if row["name"] in names:
                raise ValueError(f"Duplicate name on CSV row {line}")
            names.add(row["name"])
            rows.append(row)
    return rows


def launch(row, options, password=None, auth_only=False):
    password = row["password"] if password is None else password
    if not password or any(c in password for c in "\r\n"):
        raise ValueError("Enter a one-line password")
    domain, separator, user = row["domain_user"].partition("\\")
    args = [f"/v:{row['ip']}", f"/u:{user if separator else domain}"]
    if separator:
        args.append(f"/d:{domain}")
    args.extend(options)
    if auth_only:
        args.extend(["+auth-only", "/timeout:10000"])
    else:
        args.extend(["/timeout:10000", "/log-level:DEBUG",
                     "/log-filters:com.freerdp.core.rdp:DEBUG,com.freerdp.*:WARN,com.winpr.*:WARN"])
    args.append(f"/p:{password}")
    read_fd, write_fd = os.pipe()
    try:
        process = subprocess.Popen(
            ["xfreerdp", f"/args-from:fd:{read_fd}"], pass_fds=(read_fd,),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except OSError:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
    try:
        with os.fdopen(write_fd, "w") as arguments:
            arguments.write("\n".join(args) + "\n")
        if auth_only:
            output, _ = process.communicate(timeout=15)
            return subprocess.CompletedProcess([], process.returncode, output)
        # Track activation so closing a working session can never trigger a retry.
        # Keep only a bounded log tail, even during a long-running desktop session.
        tail = deque(maxlen=256)
        started = False
        for line in process.stdout:
            started = started or "--> CONNECTION_STATE_ACTIVE" in line
            tail.append(line)
        result = subprocess.CompletedProcess([], process.wait(), "".join(tail))
        result.session_started = started
        return result
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess([], 1, "ERRCONNECT_CONNECT_FAILED")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def connection_error(result, auth_only=False):
    output = result.stdout
    if not auth_only and getattr(result, "session_started", False):
        return None
    # FreeRDP 3 can return zero for failed NLA. Its auth-only result is definitive.
    if auth_only and "Authentication only, exit status 1" in output:
        return None
    if any(code in output for code in ("ACCOUNT_LOCKED_OUT", "ACCOUNT_DISABLED")):
        return "Windows account is locked or disabled. Contact your administrator."
    if any(code in output for code in ("PASSWORD_EXPIRED", "PASSWORD_MUST_CHANGE")):
        return "Windows password must be changed before connecting."
    if any(code in output for code in ("LOGON_FAILURE", "AUTHENTICATION_FAILED", "WRONG_PASSWORD")):
        return "Windows rejected this login. Check your password and try again."
    if "ERRCONNECT_" in output or (auth_only and "exit status 0" in output):
        return "Could not connect. Check that this PC is online, then try again."
    if result.returncode != 0 or auth_only or getattr(result, "session_started", None) is False:
        return "Connection failed. Check your login and try again."
    return None


def connect_with_retry(row, options, password=None, auth_only=False):
    transient = ("ERRCONNECT_CONNECT_TRANSPORT_FAILED", "ERRCONNECT_CONNECT_FAILED",
                 "ERRCONNECT_DNS_NAME_NOT_FOUND", "ERRCONNECT_TLS_CONNECT_FAILED",
                 "ERRCONNECT_SECURITY_NEGO_CONNECT_FAILED", "ERRCONNECT_CONNECT_ACTIVATION_TIMEOUT",
                 "ERRCONNECT_PRE_CONNECT_FAILED", "ERRCONNECT_POST_CONNECT_FAILED")
    terminal = ("LOGON_FAILURE", "AUTHENTICATION_FAILED", "WRONG_PASSWORD", "ACCOUNT_",
                "PASSWORD_EXPIRED", "PASSWORD_MUST_CHANGE", "ERRCONNECT_CERT_CONNECT_ERROR",
                "REMOTE HOST IDENTIFICATION HAS CHANGED", "certificate has changed")
    for attempt in range(3):
        result = launch(row, options, password=password, auth_only=auth_only)
        error = connection_error(result, auth_only=auth_only)
        if not error:
            return result
        if any(code in result.stdout for code in terminal):
            return result
        retryable = any(code in result.stdout for code in transient) or result.returncode < 0
        if getattr(result, "session_started", None) is False and "ERRCONNECT_CONNECT_CANCELLED" not in result.stdout:
            retryable = True
        if not retryable:
            return result
        if attempt < 2:
            print(f"Remote PC: transient startup failure; retry {attempt + 1}/2", file=sys.stderr)
            time.sleep(0.75 * (attempt + 1))
    return result


def popup_worker(row, options, source=None, emit=None):
    source = sys.stdin if source is None else source
    if emit is None:
        emit = lambda message: print(json.dumps(message), flush=True)
    for line in source:
        try:
            request = json.loads(line)
            password = request.get("password", "")
            if not isinstance(password, str) or not password or any(c in password for c in "\r\n"):
                emit({"error": "Enter a one-line password."})
                continue
            result = connect_with_retry(row, options, password=password, auth_only=True)
            error = connection_error(result, auth_only=True)
            if error:
                emit({"error": error})
                continue
            emit({"connected": True})
            result = connect_with_retry(row, options, password=password)
            error = connection_error(result)
            if error:
                emit({"error": error})
                continue
            emit({"finished": True})
            return 0
        except (OSError, ValueError):
            emit({"error": "Could not start the connection. Please try again."})
    return 0


def password_popup(args, error=""):
    env = {**os.environ, "RDP_POPUP_CSV": args.csv_file,
           "RDP_POPUP_OPTIONS": args.options_file, "RDP_POPUP_NAME": args.launch,
           "RDP_POPUP_ERROR": error, "RDP_POPUP_PYTHON": sys.executable,
           "RDP_POPUP_SCRIPT": str(Path(__file__).resolve())}
    popup = Path(__file__).resolve().parents[2] / "desktop/quickshell/config/RdpPasswordPopup.qml"
    return subprocess.run(
        ["quickshell", "--path", str(popup)],
        env=env,
    ).returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file")
    parser.add_argument("options_file")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true")
    action.add_argument("--launch", metavar="NAME")
    action.add_argument("--popup-worker", metavar="NAME")
    args = parser.parse_args()
    try:
        rows = read_remotes(args.csv_file)
        if args.list:
            print(json.dumps([{**{key: row[key] for key in ("name", "ip", "domain_user")},
                               "password_set": bool(row["password"])} for row in rows]))
            return 0
        row = next((row for row in rows if row["name"] == (args.launch or args.popup_worker)), None)
        if row is None:
            raise ValueError("Remote no longer exists in the CSV; reopen the picker")
        with open(args.options_file) as source:
            options = json.load(source)
        if args.popup_worker:
            # Quickshell terminates this worker on Cancel; also clean up its client.
            signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
            return popup_worker(row, options)
        if not row["password"]:
            return password_popup(args)
        error = connection_error(connect_with_retry(row, options))
        return password_popup(args, error) if error else 0
    except (OSError, ValueError) as error:
        message = str(error)
        print(message, file=sys.stderr)
        subprocess.run(["notify-send", "Remote PC", message], check=False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
