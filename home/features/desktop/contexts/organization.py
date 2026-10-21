"""Portable organizational layout, independent of context storage and runtimes.

One atomic document makes batch reparenting indivisible to the catalog watcher
and Syncthing. Unknown IDs are retained for contexts that have not arrived yet.
Undo is machine-local and refuses to overwrite intervening remote changes.
"""

import copy
from pathlib import Path
import subprocess
import uuid

import contextctl as ctl


def layout_path():
    return ctl.root() / ".context-layout.json"


def load():
    conflicts = list(ctl.root().glob(".context-layout.sync-conflict*.json"))
    if conflicts:
        raise ctl.ContextError("Context layout has a Syncthing conflict; resolve it before organizing")
    data = ctl.read_json(layout_path(), {"version": 1, "nodes": {}})
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("nodes"), dict):
        raise ctl.ContextError("Invalid context organization layout")
    for key, entry in data["nodes"].items():
        if (not isinstance(entry, dict) or not isinstance(key, str)
                or not isinstance(entry.get("label"), str)
                or (entry.get("parent_id") is not None and not isinstance(entry.get("parent_id"), str))):
            raise ctl.ContextError("Invalid context organization entry")
        label(entry["label"])
    return data


def label(value):
    ctl.relative_name(value, leaf=True)
    return value


def group_id(path):
    return "group-" + str(uuid.uuid5(uuid.NAMESPACE_URL, "desktop-context-group:" + path))


def resolve(contexts, layout=None):
    layout = load() if layout is None else layout
    by_path = {Path(item["name"]): item["id"] for item in contexts}
    # Legacy directory-only containers remain navigable and editable.
    for path in list(by_path):
        for ancestor in path.parents:
            if ancestor != Path("."):
                by_path.setdefault(ancestor, group_id(ancestor.as_posix()))
    nodes = {}
    by_id = {item["id"]: item for item in contexts}
    for path, identifier in by_path.items():
        context = by_id.get(identifier)
        nodes[identifier] = {
            "id": identifier, "label": path.name,
            "parent_id": by_path.get(path.parent), "is_group": context is None,
            "path": context["path"] if context else str(ctl.root() / path),
            "cwd": context["cwd"] if context else str(ctl.root() / path),
            "working_directory": context.get("working_directory", ".") if context else ".",
            "working_directory_path": context.get("working_directory_path", context["cwd"]) if context else str(ctl.root() / path),
            "working_directory_available": context.get("working_directory_available", True) if context else True,
            "runtime_id": context.get("runtime_id") if context else None,
            "window_count": context.get("window_count", 0) if context else 0,
        }
    # Retain empty legacy groups once explicitly edited.
    for identifier, entry in layout["nodes"].items():
        if identifier not in nodes and entry.get("group_path"):
            path = entry["group_path"]
            ctl.relative_name(path)
            nodes[identifier] = {"id": identifier, "label": entry["label"],
                                 "parent_id": None, "is_group": True,
                                 "path": str(ctl.root() / path), "cwd": str(ctl.root() / path),
                                 "runtime_id": None, "window_count": 0}
        if identifier in nodes:
            nodes[identifier].update(label=entry["label"], parent_id=entry["parent_id"])
    for node in nodes.values():
        node["unplaced"] = node["parent_id"] is not None and node["parent_id"] not in nodes
        if node["unplaced"]:
            node["missing_parent_id"] = node["parent_id"]
            node["parent_id"] = None
    for node in nodes.values():
        seen = {node["id"]}
        ancestors = []
        parent = node["parent_id"]
        while parent is not None:
            if parent in seen:
                raise ctl.ContextError("Context hierarchy contains a cycle")
            seen.add(parent)
            ancestors.insert(0, parent)
            parent = nodes[parent]["parent_id"]
        node["ancestors"] = ancestors
        node["breadcrumb"] = " / ".join(nodes[key]["label"] for key in [*ancestors, node["id"]])
        node["child_count"] = sum(other["parent_id"] == node["id"] for other in nodes.values())
    return sorted(nodes.values(), key=lambda node: (node["label"].casefold(), node["id"]))


def entry(node):
    result = {"label": node["label"], "parent_id": node["parent_id"]}
    if node["is_group"]:
        result["group_path"] = str(Path(node["path"]).relative_to(ctl.root()))
    return result


def history_path():
    return ctl.state_root() / "organization-undo.json"


def history():
    data = ctl.read_json(history_path(), {"entries": []})
    return data.get("entries", []) if isinstance(data, dict) else []


def can_undo():
    records = history()
    return bool(records and records[-1].get("after") == load())


def commit(before, after, description):
    if before == after:
        return
    records = history()
    if records and records[-1].get("after") != before:
        records = []
    # Write layout before history: failure can omit an undo but never invent one.
    ctl.atomic_json(layout_path(), after)
    ctl.atomic_json(history_path(), {"entries": [*records[-29:], {
        "before": before, "after": after, "description": description,
    }]})


def change(identifiers, parent=None, new_label=None):
    before = load()
    contexts = ctl.scan()
    nodes = {node["id"]: node for node in resolve(contexts, before)}
    identifiers = list(dict.fromkeys(identifiers))
    if not identifiers or any(identifier not in nodes for identifier in identifiers):
        raise ctl.ContextError("Select existing contexts to organize")
    if new_label is not None:
        if len(identifiers) != 1:
            raise ctl.ContextError("Rename one context at a time")
        label(new_label)
    elif parent is not None and parent not in nodes:
        raise ctl.ContextError("Destination no longer exists")
    after = copy.deepcopy(before)
    for identifier in identifiers:
        node = nodes[identifier]
        # Moving an ancestor already carries selected descendants with it.
        if new_label is None and any(ancestor in identifiers for ancestor in node["ancestors"]):
            continue
        value = entry(node)
        if new_label is not None:
            value["label"] = new_label
        else:
            value["parent_id"] = parent
        after["nodes"][identifier] = value
    resolved = resolve(contexts, after)
    for item in resolved:
        if item["id"] not in identifiers:
            continue
        if any(other["id"] != item["id"] and other["parent_id"] == item["parent_id"]
               and other["label"].casefold() == item["label"].casefold() for other in resolved):
            raise ctl.ContextError(f"A context named {item['label']!r} already exists at that level")
    if load() != before:
        raise ctl.ContextError("Layout changed while organizing; try again")
    commit(before, after, "Rename context" if new_label is not None else "Move contexts")


def create(name, parent=None):
    label(name)
    before = load()
    nodes = resolve(ctl.scan(), before)
    if parent is not None and not any(node["id"] == parent for node in nodes):
        raise ctl.ContextError("Destination no longer exists")
    if any(node["parent_id"] == parent and node["label"].casefold() == name.casefold() for node in nodes):
        raise ctl.ContextError("A context with that name already exists at this level")
    # Unique storage directory; display names and organization can change freely.
    storage = name
    if (ctl.root() / storage).exists():
        storage = name + "-" + str(uuid.uuid4())[:8]
    data = ctl.create(storage, locked=True)
    if load() != before:
        raise ctl.ContextError("Layout changed during creation; new context remains at top level")
    after = copy.deepcopy(before)
    after["nodes"][data["id"]] = {"label": name, "parent_id": parent}
    ctl.atomic_json(layout_path(), after)
    # Creating a notebook is deliberately not undone by deleting its files.
    ctl.atomic_json(history_path(), {"entries": []})
    return data["id"]


def promote(identifier):
    """Give a legacy directory-only group a notebook and persistent identity."""
    before = load()
    node = next((node for node in resolve(ctl.scan(), before) if node["id"] == identifier), None)
    if not node or not node["is_group"]:
        raise ctl.ContextError("Select a directory-only group to make into a context")
    relative = str(Path(node["path"]).relative_to(ctl.root()))
    data = ctl.create(relative, locked=True)
    after = copy.deepcopy(before)
    after["nodes"].pop(identifier, None)
    after["nodes"][data["id"]] = {"label": node["label"], "parent_id": node["parent_id"]}
    for value in after["nodes"].values():
        if value["parent_id"] == identifier:
            value["parent_id"] = data["id"]
    ctl.atomic_json(layout_path(), after)
    ctl.atomic_json(history_path(), {"entries": []})
    return data["id"]


def undo():
    records = history()
    if not records:
        raise ctl.ContextError("No organizational changes to undo")
    if records[-1]["after"] != load():
        raise ctl.ContextError("Layout changed elsewhere; cannot undo over those changes")
    resolve(ctl.scan(), records[-1]["before"])
    ctl.atomic_json(layout_path(), records[-1]["before"])
    ctl.atomic_json(history_path(), {"entries": records[:-1]})


def trash_contexts(identifiers):
    """Trash closed leaves only. Logical nesting never authorizes deleting an
    unrelated physical descendant. Historical Git exclusions remain intact.
    Caller holds the context mutation lock and has obtained confirmation.
    """
    before = load()
    catalog = ctl.catalog()
    nodes = {node["id"]: node for node in catalog["nodes"]}
    identifiers = list(dict.fromkeys(identifiers))
    if not identifiers or any(identifier not in nodes for identifier in identifiers):
        raise ctl.ContextError("Select existing contexts to delete")
    selected = [nodes[identifier] for identifier in identifiers]
    for node in selected:
        if node["runtime_id"]:
            raise ctl.ContextError(f"Close running context {node['label']!r} before deleting it")
        if node["child_count"]:
            raise ctl.ContextError(f"Move children out of {node['label']!r} before deleting it")
        directory = Path(node["path"])
        if directory == ctl.root() or directory.resolve() != directory or not directory.is_dir():
            raise ctl.ContextError(f"Context directory is missing or redirected: {directory}")
        if any(other["id"] != node["id"] and Path(other["path"]).is_relative_to(directory)
               for other in catalog["contexts"]):
            raise ctl.ContextError(f"Directory for {node['label']!r} still contains other contexts; move them physically before deleting")
    if any(ctl.note_context(client, selected) is not None for client in ctl.clients()):
        raise ctl.ContextError("Close selected context notebooks before deleting")
    after = copy.deepcopy(before)
    for node in selected:
        if load() != after:
            raise ctl.ContextError("Layout changed before deletion; select contexts again")
        result = subprocess.run(["gio", "trash", "--", node["path"]], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise ctl.ContextError(result.stderr.strip() or f"Could not move {node['label']!r} to Trash")
        if node["is_group"]:
            after["nodes"].pop(node["id"], None)
        else:
            # Unknown context UUIDs are dormant, so retaining its label/parent
            # restores organization too if its directory is restored from Trash.
            after["nodes"][node["id"]] = entry(node)
        ctl.atomic_json(layout_path(), after)
        # Trash restoration is handled by the file manager, not layout undo.
        ctl.atomic_json(history_path(), {"entries": []})
