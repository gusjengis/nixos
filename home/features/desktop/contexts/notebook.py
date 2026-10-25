"""Shared context notebook setup. Native Bases owns cards; the plugin owns events."""

import json
import os
import re
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import contextctl as ctl
import yaml

SOURCE = Path(__file__).parent / "notebook"
PLUGIN = "context-notebook"
PHASES = ("Thoughts", "Todo", "In-Progress", "Done")
ALIASES = {name.lower(): name for name in PHASES} | {
    "idea": "Thoughts", "ideas": "Thoughts", "outstanding questions": "Thoughts",
}
FRONTMATTER = re.compile(r"\A(\ufeff?---[ \t]*\r?\n)(.*?)(^---[ \t]*(?:\r?\n|\Z))", re.MULTILINE | re.DOTALL)


def timestamp(seconds=None):
    value = datetime.fromtimestamp(seconds, timezone.utc) if seconds is not None else datetime.now(timezone.utc)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def read(path):
    with path.open(newline="") as stream:
        return stream.read()


def json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def write(path, text):
    if path.exists() and read(path) == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".contextctl-", delete=False) as stream:
            temporary = stream.name
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return True


def merge_json(path, changes):
    value = ctl.read_json(path, {})
    if not isinstance(value, dict):
        raise ctl.ContextError(f"Invalid notebook configuration: {path}")
    updated = value | changes
    if updated != value or not path.exists():
        ctl.atomic_json(path, updated)


def fields(text):
    match = FRONTMATTER.match(text)
    if not match:
        if re.match(r"\ufeff?---[ \t]*\r?\n", text):
            raise ctl.ContextError("Unterminated note frontmatter")
        return None, {}, None
    try:
        node = yaml.compose(match[2])
        value = yaml.safe_load(match[2]) or {}
    except yaml.YAMLError as exc:
        raise ctl.ContextError(f"Invalid note frontmatter: {exc}") from exc
    if not isinstance(value, dict):
        raise ctl.ContextError("Note frontmatter must be a mapping")
    return match, value, node


def eligible(path, value):
    return (not any(part.startswith(".") for part in path.parts)
            and path.parts[0] not in ("Templates", "Attachments") and value.get("kanban") is not False)


def update_note(path, now):
    text = read(path)
    _, value, _ = fields(text)
    status = value.get("status")
    status = "Thoughts" if status in (None, "") else ALIASES.get(str(status).strip().lower(), status)
    if status not in PHASES:
        raise ctl.ContextError(f"Unknown Kanban status in {path}: {status!r}")
    changes = {}
    if value.get("status") != status:
        changes["status"] = status
    if not value.get("created"):
        stat = path.stat()
        birth = getattr(stat, "st_birthtime", None)
        changes["created"] = timestamp(birth if birth is not None else stat.st_mtime)
        changes["created-source"] = "filesystem-birthtime" if birth is not None else "filesystem-mtime-estimate"
    history = value.get("kanban-history", [])
    if not isinstance(history, list) or any(not isinstance(event, dict) for event in history):
        raise ctl.ContextError(f"Invalid kanban-history in {path}")
    if not history or history[-1].get("status") != status:
        changes["kanban-history"] = [*history, {"status": status, "at": now, "event": "observed"}]
    if not changes:
        return False
    return write(path, edit_fields(text, changes))


def edit_fields(text, changes):
    """Render changed properties without rewriting unrelated YAML or note content."""
    changes = dict(changes)
    match, _, node = fields(text)
    if match:
        header = match[2]
        # Replace only changed YAML values, preserving comments, other properties,
        # and the exact note body. JSON flow values are valid YAML.
        replacements = []
        for key_node, value_node in node.value if node else []:
            key = key_node.value
            if key in changes:
                old = header[value_node.start_mark.index:value_node.end_mark.index]
                replacement = " " + json.dumps(changes.pop(key), ensure_ascii=False, default=json_default)
                if old.endswith("\n"):
                    replacement += "\n"
                replacements.append((value_node.start_mark.index, value_node.end_mark.index, replacement))
        for start, end, replacement in sorted(replacements, reverse=True):
            header = header[:start] + replacement + header[end:]
        if header and not header.endswith("\n"):
            header += "\n"
        header += "".join(f"{key}: {json.dumps(item, ensure_ascii=False, default=json_default)}\n" for key, item in changes.items())
        updated = match[1] + header + match[3] + text[match.end():]
    else:
        header = "".join(f"{key}: {json.dumps(item, ensure_ascii=False, default=json_default)}\n" for key, item in changes.items())
        updated = "---\n" + header + "---\n" + text
    # Catch malformed edits before publishing anything.
    fields(updated)
    return updated


def remove_home(vault):
    moved = []
    for path in (vault / "Home.md", vault / "Home.md.md"):
        if not path.is_file():
            continue
        text = read(path)
        remainder = re.sub(r"(?m)^# .*\n|^## (Now|Next|Working Notes|Return Point)\s*$|^- \[ \]\s*$", "", text)
        # Keep real content as an ordinary card; discard only empty starter scaffolding.
        destination = vault / "Notebook Notes.md" if remainder.strip() else vault / ".trash" / path.name
        ctl.contained(vault, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        base, index = destination, 2
        while destination.exists():
            destination = base.with_name(f"{base.stem} {index}{base.suffix}")
            index += 1
        path.rename(destination)
        moved.append((path.name, destination.relative_to(vault).as_posix()))
    return moved


def setup(vault, *, force=False):
    vault = Path(vault)
    config = ctl.contained(vault, vault / ".obsidian")
    marker = config / "context-notebook.json"
    if not force and ctl.read_json(marker, {}).get("version") == 1:
        return {"vault": str(vault), "updated": 0, "homes": []}
    config.mkdir(parents=True, exist_ok=True)
    # Validate all cards before changing this vault.
    for path in vault.rglob("*.md"):
        relative = path.relative_to(vault)
        if path.is_symlink() or any(part.startswith(".") for part in relative.parts):
            continue
        ctl.contained(vault, path)
        _, value, _ = fields(read(path))
        if eligible(relative, value):
            status = value.get("status")
            if status not in (None, "") and ALIASES.get(str(status).strip().lower(), status) not in PHASES:
                raise ctl.ContextError(f"Unknown Kanban status in {path}: {status!r}")
    homes = remove_home(vault)
    count, now = 0, timestamp()
    for path in vault.rglob("*.md"):
        relative = path.relative_to(vault)
        if path.is_symlink() or any(part.startswith(".") for part in relative.parts):
            continue
        _, value, _ = fields(read(path))
        if eligible(relative, value):
            count += update_note(path, now)
    board = vault / "Kanban.base"
    if not board.exists():
        write(board, (SOURCE / "Kanban.base").read_text())
    merge_json(config / "app.json", {"newFileLocation": "root"})
    core_path = config / "core-plugins.json"
    core = ctl.read_json(core_path, {})
    if isinstance(core, list):
        if "bases" not in core:
            ctl.atomic_json(core_path, [*core, "bases"])
    else:
        merge_json(core_path, {"bases": True})
    plugin_path = config / "plugins" / PLUGIN
    plugin_path.parent.mkdir(parents=True, exist_ok=True)
    target = SOURCE / "plugin"
    if plugin_path.is_symlink():
        if plugin_path.readlink() != target:
            plugin_path.unlink()
            plugin_path.symlink_to(target, target_is_directory=True)
    elif not plugin_path.exists():
        plugin_path.symlink_to(target, target_is_directory=True)
    else:
        raise ctl.ContextError(f"Unmanaged plugin directory: {plugin_path}")
    enabled_path = config / "community-plugins.json"
    enabled = ctl.read_json(enabled_path, [])
    if not isinstance(enabled, list):
        raise ctl.ContextError(f"Invalid plugin list: {enabled_path}")
    if PLUGIN not in enabled:
        ctl.atomic_json(enabled_path, [*enabled, PLUGIN])
    merge_json(marker, {"version": 1})
    return {"vault": str(vault), "updated": count, "homes": homes}


def enable_profile(profile, vault_id):
    """Seed plugin consent in a closed, context-owned Chromium profile only.

    Chromium's LevelDB lock prevents editing a live profile. No browser history,
    credentials, or unrelated localStorage keys are touched.
    """
    import plyvel

    storage = profile / "Local Storage" / "leveldb"
    storage.mkdir(parents=True, exist_ok=True)
    origin = b"app://obsidian.md"
    key = b"_" + origin + b"\x00\x01enable-plugin-" + vault_id.encode()
    try:
        with plyvel.DB(str(storage), create_if_missing=True) as database:
            if database.get(key) != b"\x01true":
                database.put(b"VERSION", b"1")
                database.put(key, b"\x01true", sync=True)
    except plyvel.Error as exc:
        raise ctl.ContextError(f"Close the context notebook before enabling its shared plugin: {exc}") from exc
