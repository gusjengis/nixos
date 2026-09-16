#!/usr/bin/env python3

import fcntl
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path


CONFIG_PATH = Path(os.environ["QUICKSHELL_SEARCH_CONFIG"])
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "quickshell"
USAGE_PATH = STATE_DIR / "launcher-usage.json"
LOCK_PATH = STATE_DIR / "launcher-usage.lock"


def config():
    settings = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings["_directory"] = CONFIG_PATH.parent
    return settings


def expand_path(raw_path, base=None):
    expanded = Path(os.path.expandvars(os.path.expanduser(raw_path)))
    if not expanded.is_absolute() and base:
        expanded = base / expanded
    return expanded.resolve()


def read_usage():
    try:
        return json.loads(USAGE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, TypeError):
        return {"apps": {}, "projects": {}}


def record_usage(kind, key):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        usage = read_usage()
        entries = usage.setdefault(kind, {})
        current = entries.get(key, {})
        entries[key] = {
            "count": int(current.get("count", 0)) + 1,
            "lastUsed": int(time.time()),
        }
        temporary = USAGE_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(usage), encoding="utf-8")
        temporary.replace(USAGE_PATH)


SEPARATORS = " -_/\\.:,@+"


def normalize_text(value):
    return "".join(" " if character in SEPARATORS else character for character in value.lower())


def token_score(candidate, token):
    position = -1
    score = 0
    for character in token:
        next_position = candidate.find(character, position + 1)
        if next_position < 0:
            return None
        score += 8 if next_position == position + 1 else 1
        if next_position == 0 or candidate[next_position - 1] == " ":
            score += 5
        position = next_position
    return score


def fuzzy_score(value, query):
    candidate = normalize_text(value)
    tokens = normalize_text(query).split()
    if not tokens:
        return 0
    score = 0
    for token in tokens:
        matched = token_score(candidate, token)
        if matched is None:
            return None
        score += matched
        if token in candidate:
            score += len(token) * 4
        if candidate.startswith(token):
            score += 10
    return score - len(candidate) * 0.01


def repo_destination(entry):
    parent, separator, url = entry.partition(";")
    if not separator:
        return None
    repository = url.strip().rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if repository.endswith(".git"):
        repository = repository[:-4]
    return expand_path(parent.strip()) / repository


def project_paths(settings):
    projects = {}
    config_directory = settings["_directory"]
    list_directory = expand_path(settings["repoListDirectory"], config_directory)
    if list_directory.is_dir():
        for list_path in sorted(list_directory.glob("*.list")):
            for line in list_path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                destination = repo_destination(stripped)
                if destination:
                    projects[str(destination.resolve())] = {}

    ignored = {str(expand_path(path)) for path in settings.get("ignore", [])}
    for raw_root in settings.get("roots", []):
        root = expand_path(raw_root)
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if child.is_dir() and str(child.resolve()) not in ignored:
                projects.setdefault(str(child.resolve()), {})

    for entry in settings.get("projects", []):
        project = {"path": entry} if isinstance(entry, str) else entry
        path = str(expand_path(project["path"]))
        projects[path] = {"profile": project.get("profile")}

    for raw_path, profile in settings.get("overrides", {}).items():
        path = str(expand_path(raw_path))
        projects.setdefault(path, {})["profile"] = profile
    return projects


def list_projects(query):
    settings = config()
    usage = read_usage().get("projects", {})
    default_profile = settings["defaultProfile"]
    profiles = settings["profiles"]
    if default_profile not in profiles:
        raise ValueError(f"unknown default project profile: {default_profile}")
    results = []
    validated_profiles = set()
    for raw_path, metadata in project_paths(settings).items():
        path = Path(raw_path)
        if not path.is_dir():
            continue
        try:
            relative_parent = path.parent.relative_to(Path.home())
            display_parent = "~" if str(relative_parent) == "." else "~/" + str(relative_parent)
        except ValueError:
            display_parent = str(path.parent)
        score = fuzzy_score(f"{path.name} {display_parent}", query)
        if score is None:
            continue
        frequency = usage.get(raw_path, {})
        profile = metadata.get("profile") or default_profile
        if profile not in profiles:
            raise ValueError(f"unknown project profile for {path}: {profile}")
        if profile not in validated_profiles:
            profile_config = profiles[profile]
            commands = [profile_config.get("command", [])]
            if profile_config.get("type") == "tmux":
                commands = [["create-tmux-session"], profile_config.get("terminal", [])]
            missing = [command[0] for command in commands if command and not shutil.which(command[0])]
            if missing:
                raise ValueError(f"project profile {profile} needs missing command: {missing[0]}")
            validated_profiles.add(profile)
        results.append({
            "kind": "project",
            "name": path.name,
            "description": display_parent,
            "path": raw_path,
            "profile": profile,
            "count": int(frequency.get("count", 0)),
            "lastUsed": int(frequency.get("lastUsed", 0)),
            "score": score,
        })
    results.sort(key=lambda item: (-item["count"], -item["lastUsed"], -item["score"], item["name"].lower()))
    for result in results:
        print(json.dumps(result), flush=True)


def substitute(arguments, **values):
    return [argument.format(**values) for argument in arguments]


def lua_string(value):
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def dispatch(lua):
    # This Hyprland fork evaluates `hyprctl dispatch` as Lua, so classic
    # `dispatch exec [workspace ...]` syntax is a silent no-op here.
    result = subprocess.run(["hyprctl", "dispatch", lua], capture_output=True, text=True)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0 or output != "ok":
        raise RuntimeError(f"hyprctl dispatch failed ({lua}): {output}")


def exec_on_workspace(command, workspace):
    dispatch(f"hl.dsp.exec_cmd({lua_string(shlex.join(command))}, {{ workspace = {lua_string(workspace)} }})")


def show_special_workspace(name):
    # `toggle_special` races window creation and can hide what was just shown;
    # focusing the workspace is idempotent.
    dispatch(f"hl.dsp.focus({{ workspace = {lua_string('special:' + name)} }})")


def workspace_has_windows(name):
    result = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    try:
        return any(client.get("workspace", {}).get("name") == name for client in json.loads(result.stdout))
    except json.JSONDecodeError:
        return False


def process_has_ancestor(pid, ancestors):
    while pid > 1:
        if pid in ancestors:
            return True
        try:
            fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()
            pid = int(fields[1])
        except (OSError, ValueError, IndexError):
            return False
    return False


def terminal_tmux_client():
    windows = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True)
    if windows.returncode != 0:
        return None
    try:
        terminal_pids = {
            int(client["pid"])
            for client in json.loads(windows.stdout)
            if client.get("workspace", {}).get("name") == "special:terminal"
        }
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None
    clients = subprocess.run(
        ["tmux", "list-clients", "-F", "#{client_activity}\t#{client_tty}\t#{client_pid}"],
        capture_output=True,
        text=True,
    )
    if clients.returncode != 0:
        return None
    matches = []
    for line in clients.stdout.splitlines():
        activity, tty, raw_pid = line.split("\t", 2)
        if process_has_ancestor(int(raw_pid), terminal_pids):
            matches.append((int(activity), tty))
    return max(matches)[1] if matches else None


def open_project(raw_path, profile_name, current_workspace=False):
    settings = config()
    path = expand_path(raw_path)
    profile = settings["profiles"][profile_name]
    record_usage("projects", str(path))
    if profile["type"] == "command":
        subprocess.Popen(
            substitute(profile["command"], path=str(path)),
            cwd=path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return
    if profile["type"] != "tmux":
        raise ValueError(f"unknown project profile type: {profile['type']}")

    session = subprocess.run(
        ["create-tmux-session", str(path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    terminal = substitute(profile["terminal"], path=str(path), session=session)
    if current_workspace:
        subprocess.Popen(terminal, cwd=path, start_new_session=True)
        return

    client = terminal_tmux_client()
    if client:
        subprocess.run(["tmux", "switch-client", "-c", client, "-t", session], check=True)
    else:
        exec_on_workspace(terminal, "special:terminal")
        for _ in range(500):
            if workspace_has_windows("special:terminal"):
                break
            time.sleep(0.02)
    show_special_workspace("terminal")


def web_url(query, settings):
    candidate = query.strip()
    parsed = urllib.parse.urlparse(candidate if "://" in candidate else f"https://{candidate}")
    if parsed.hostname and ("." in parsed.hostname or parsed.hostname == "localhost") and " " not in candidate:
        return parsed.geturl()
    return settings["webSearchUrl"].replace("{query}", urllib.parse.quote_plus(candidate))


def chromium_open():
    result = subprocess.run(["hyprctl", "-j", "clients"], capture_output=True, text=True)
    if result.returncode != 0:
        return False
    try:
        return any("chromium" in client.get("class", "").lower() for client in json.loads(result.stdout))
    except json.JSONDecodeError:
        return False


def open_web(query):
    url = web_url(query, config())
    if chromium_open():
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return

    exec_on_workspace(["chromium", url], "special:browser")
    for _ in range(500):
        if workspace_has_windows("special:browser"):
            show_special_workspace("browser")
            return
        time.sleep(0.02)
    raise RuntimeError("Chromium did not open on special:browser")


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "projects" and len(sys.argv) == 3:
        list_projects(sys.argv[2])
        return
    if command == "record-app" and len(sys.argv) == 3:
        record_usage("apps", sys.argv[2])
        return
    if command == "open-project" and len(sys.argv) in (4, 5):
        open_project(sys.argv[2], sys.argv[3], len(sys.argv) == 5 and sys.argv[4] == "--current")
        return
    if command == "web" and len(sys.argv) == 3:
        open_web(sys.argv[2])
        return
    raise SystemExit("usage: quickshell-search {projects|record-app|open-project|web} ...")


if __name__ == "__main__":
    try:
        main()
    except (json.JSONDecodeError, KeyError, OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"quickshell-search: {error}", file=sys.stderr)
        raise SystemExit(1)
