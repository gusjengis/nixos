"""Read private RDP rows at runtime; never expose passwords in argv or listings."""

import argparse
import csv
import ipaddress
import json
import os
import subprocess
import sys


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


def launch(row, options):
    if not row["password"]:
        raise ValueError(f"Password missing for {row['name']}; fill its password cell in the CSV")
    domain, separator, user = row["domain_user"].partition("\\")
    args = [f"/v:{row['ip']}", f"/u:{user if separator else domain}"]
    if separator:
        args.append(f"/d:{domain}")
    args.extend(options)
    args.append(f"/p:{row['password']}")
    read_fd, write_fd = os.pipe()
    try:
        process = subprocess.Popen(["xfreerdp", f"/args-from:fd:{read_fd}"], pass_fds=(read_fd,))
    except OSError:
        os.close(write_fd)
        raise
    finally:
        os.close(read_fd)
    with os.fdopen(write_fd, "w") as arguments:
        arguments.write("\n".join(args) + "\n")
    return process.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file")
    parser.add_argument("options_file")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--list", action="store_true")
    action.add_argument("--launch", metavar="NAME")
    args = parser.parse_args()
    try:
        rows = read_remotes(args.csv_file)
        if args.list:
            print(json.dumps([{**{key: row[key] for key in ("name", "ip", "domain_user")},
                               "password_set": bool(row["password"])} for row in rows]))
            return 0
        row = next((row for row in rows if row["name"] == args.launch), None)
        if row is None:
            raise ValueError("Remote no longer exists in the CSV; reopen the picker")
        with open(args.options_file) as source:
            options = json.load(source)
        return launch(row, options)
    except (OSError, ValueError) as error:
        message = str(error)
        print(message, file=sys.stderr)
        subprocess.run(["notify-send", "Remote PC", message], check=False)
        return 1


if __name__ == "__main__":
    sys.exit(main())
