#!/usr/bin/env python3
"""JSON command bridge for Quickshell system controls."""

import csv
import json
import os
import re
import subprocess
import sys


MAC_ADDRESS = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")
COMMANDS = {
    "wifi-state": (0, 0),
    "wifi-power": (1, 1),
    "wifi-scan": (0, 0),
    "wifi-connect": (1, 2),
    "wifi-disconnect": (0, 0),
    "bluetooth-state": (0, 0),
    "bluetooth-power": (1, 1),
    "bluetooth-scan": (0, 0),
    "bluetooth-pair": (1, 1),
    "bluetooth-connect": (1, 1),
    "bluetooth-disconnect": (1, 1),
    "bluetooth-remove": (1, 1),
    "brightness-state": (0, 0),
    "brightness-set": (1, 1),
}


def emit(value):
    print(json.dumps(value, separators=(",", ":"), ensure_ascii=False))


def run(command, timeout=10, input_text=None):
    environment = os.environ.copy()
    environment.update({"LC_ALL": "C", "NO_COLOR": "1", "SYSTEMD_COLORS": "0"})
    try:
        result = subprocess.run(
            command,
            stdin=None if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=environment,
            check=False,
            input=input_text,
        )
    except OSError as error:
        raise RuntimeError(f"{command[0]} is unavailable: {error.strerror or error}") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{command[0]} timed out") from error
    if result.returncode:
        message = (result.stderr or result.stdout).strip().replace("\n", "; ")
        raise RuntimeError(message or f"{command[0]} failed")
    return result.stdout


def split_nmcli(line):
    """Split nmcli terse output while decoding its backslash escapes."""
    fields = []
    field = []
    escaped = False
    for character in line.rstrip("\n"):
        if escaped:
            field.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(field))
            field = []
        else:
            field.append(character)
    if escaped:
        field.append("\\")
    fields.append("".join(field))
    return fields


def signal_value(value):
    try:
        return max(0, min(100, int(value)))
    except ValueError:
        return 0


def parse_wifi_networks(output):
    networks = {}
    for line in output.splitlines():
        fields = split_nmcli(line)
        if len(fields) != 4:
            continue
        active, ssid, signal, security = fields
        if not ssid:
            continue
        candidate = {
            "ssid": ssid,
            "signal": signal_value(signal),
            "security": security,
            "connected": active.strip() == "*",
        }
        existing = networks.get(ssid)
        if existing is None or (candidate["connected"], candidate["signal"]) > (
            existing["connected"], existing["signal"]
        ):
            networks[ssid] = candidate
    return sorted(networks.values(), key=lambda item: (not item["connected"], -item["signal"], item["ssid"].lower()))


def wifi_state():
    state = {"enabled": False, "connected": None, "networks": []}
    errors = []
    try:
        state["enabled"] = run(["nmcli", "-t", "-f", "WIFI", "general"]).strip() == "enabled"
    except RuntimeError as error:
        errors.append(str(error))
    if state["enabled"]:
        try:
            output = run([
                "nmcli", "-t", "--escape", "yes", "-f", "IN-USE,SSID,SIGNAL,SECURITY",
                "device", "wifi", "list", "--rescan", "no",
            ])
            state["networks"] = parse_wifi_networks(output)
            connected = next((network for network in state["networks"] if network["connected"]), None)
            if connected:
                state["connected"] = {"ssid": connected["ssid"], "signal": connected["signal"]}
        except RuntimeError as error:
            errors.append(str(error))
    if errors:
        state["error"] = "; ".join(dict.fromkeys(errors))
    return state


def parse_bluetooth_property(output, name):
    prefix = f"{name}:"
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return None


def parse_bluetooth_devices(output):
    devices = []
    for line in output.splitlines():
        match = re.match(r"^Device\s+([0-9A-Fa-f:]{17})(?:\s+(.*))?$", line.strip())
        if match and MAC_ADDRESS.fullmatch(match.group(1)):
            devices.append((match.group(1).upper(), match.group(2) or match.group(1).upper()))
    return devices


def bluetooth_state():
    state = {"powered": False, "discovering": False, "devices": []}
    errors = []
    try:
        controller = run(["bluetoothctl", "show"])
        powered = parse_bluetooth_property(controller, "Powered")
        if powered is None:
            errors.append("Bluetooth controller unavailable")
        state["powered"] = powered == "yes"
        state["discovering"] = parse_bluetooth_property(controller, "Discovering") == "yes"
    except RuntimeError as error:
        errors.append(str(error))
    try:
        known = parse_bluetooth_devices(run(["bluetoothctl", "devices"]))
        for address, fallback_name in known:
            device = {
                "address": address,
                "name": fallback_name,
                "paired": False,
                "connected": False,
                "trusted": False,
            }
            try:
                info = run(["bluetoothctl", "info", address])
                device.update({
                    "name": parse_bluetooth_property(info, "Name") or fallback_name,
                    "paired": parse_bluetooth_property(info, "Paired") == "yes",
                    "connected": parse_bluetooth_property(info, "Connected") == "yes",
                    "trusted": parse_bluetooth_property(info, "Trusted") == "yes",
                })
            except RuntimeError as error:
                errors.append(str(error))
            state["devices"].append(device)
        state["devices"].sort(key=lambda item: (not item["connected"], item["name"].lower(), item["address"]))
    except RuntimeError as error:
        errors.append(str(error))
    if errors:
        state["error"] = "; ".join(dict.fromkeys(errors))
    return state


def parse_brightness(output):
    for fields in csv.reader(output.splitlines()):
        if len(fields) < 5:
            continue
        percent_field = next((field for field in fields[2:] if field.endswith("%")), "")
        if not percent_field:
            continue
        try:
            percent = int(percent_field.removesuffix("%"))
        except ValueError:
            continue
        if 0 <= percent <= 100:
            state = {"available": True, "percent": percent}
            if fields[0]:
                state["name"] = fields[0]
            return state
    return {"available": False, "percent": 0}


def brightness_state():
    try:
        return parse_brightness(run(["brightnessctl", "--machine-readable"]))
    except RuntimeError:
        return {"available": False, "percent": 0}


def wifi_disconnect():
    output = run(["nmcli", "-t", "--escape", "yes", "-f", "DEVICE,TYPE,STATE", "device", "status"])
    devices = []
    for line in output.splitlines():
        fields = split_nmcli(line)
        if len(fields) == 3 and fields[1] == "wifi" and fields[2] in ("connected", "connecting"):
            devices.append(fields[0])
    for device in devices:
        run(["nmcli", "device", "disconnect", device])


def bluetooth_scan():
    scan_error = None
    try:
        run(["bluetoothctl", "--timeout", "5", "scan", "on"], timeout=7)
    except RuntimeError as error:
        scan_error = error
    finally:
        try:
            run(["bluetoothctl", "scan", "off"], timeout=3)
        except RuntimeError:
            pass
    if scan_error:
        raise scan_error


def require_power(value):
    if value not in ("on", "off"):
        raise ValueError("power must be on or off")
    return value


def require_address(value):
    if not MAC_ADDRESS.fullmatch(value):
        raise ValueError("invalid Bluetooth address")
    return value.upper()


def require_percent(value):
    if not re.fullmatch(r"\d{1,3}", value):
        raise ValueError("brightness percent must be an integer from 0 to 100")
    percent = int(value)
    if percent > 100:
        raise ValueError("brightness percent must be an integer from 0 to 100")
    return percent


def perform(command, arguments):
    if command == "wifi-power":
        run(["nmcli", "radio", "wifi", require_power(arguments[0])])
    elif command == "wifi-scan":
        run(["nmcli", "device", "wifi", "rescan"])
    elif command == "wifi-connect":
        invocation = ["nmcli", "device", "wifi", "connect", arguments[0]]
        if len(arguments) == 2:
            invocation.insert(1, "--ask")
            run(invocation, timeout=30, input_text=arguments[1] + "\n")
        else:
            run(invocation, timeout=30)
    elif command == "wifi-disconnect":
        wifi_disconnect()
    elif command == "bluetooth-power":
        run(["bluetoothctl", "power", require_power(arguments[0])])
    elif command == "bluetooth-scan":
        bluetooth_scan()
    elif command == "brightness-set":
        run(["brightnessctl", "set", f"{require_percent(arguments[0])}%"])
    else:
        action = command.removeprefix("bluetooth-")
        address = require_address(arguments[0])
        run(["bluetoothctl", action, address], timeout=30)
        if action == "pair":
            run(["bluetoothctl", "trust", address])


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in COMMANDS:
        emit({"ok": False, "error": "unknown or missing command"})
        return 2
    command, values = arguments[0], arguments[1:]
    minimum, maximum = COMMANDS[command]
    if not minimum <= len(values) <= maximum:
        emit({"ok": False, "error": "invalid argument count"})
        return 2
    if command == "wifi-state":
        emit(wifi_state())
        return 0
    if command == "bluetooth-state":
        emit(bluetooth_state())
        return 0
    if command == "brightness-state":
        emit(brightness_state())
        return 0
    try:
        perform(command, values)
        emit({"ok": True})
        return 0
    except (RuntimeError, ValueError) as error:
        emit({"ok": False, "error": str(error)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
