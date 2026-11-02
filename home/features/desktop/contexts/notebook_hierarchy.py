"""Immediate-child notebook mounts derived from the logical context hierarchy.

Only recorded links and empty generated group folders are removed. Original
notebooks and user folders are never moved or replaced by reconciliation.
"""

import copy
import json
import os
from pathlib import Path

import contextctl as ctl
import notebook
import yaml

MANIFEST = ".obsidian/context-hierarchy.json"
GLOBAL_ID = "cd320198-c774-58ac-a98e-3943ff8d7580"


def manifest(vault):
    path = ctl.contained(Path(vault), Path(vault) / MANIFEST)
    value = ctl.read_json(path, {})
    if not isinstance(value, dict) or not isinstance(value.get("mounts", {}), dict):
        raise ctl.ContextError(f"Invalid notebook hierarchy manifest: {vault}")
    return value


def local_path(vault, name):
    """Managed entry must not traverse an existing symlink in its parent path."""
    relative = ctl.relative_name(name)
    path = Path(vault) / relative
    ctl.contained(Path(vault), path.parent)
    return path


def plan(nodes, node):
    vault = Path(node["path"]) / ".context/notes"
    mounts, directories, labels = {}, [], {}

    def descendants(parent, prefix=Path()):
        for child in nodes:
            if child["parent_id"] == parent:
                relative = prefix / child["label"]
                if not child["is_group"]:
                    labels[relative.as_posix()] = child["breadcrumb"]
                descendants(child["id"], relative)

    def children(parent, prefix=Path()):
        for child in nodes:
            if child["parent_id"] != parent:
                continue
            relative = prefix / child["label"]
            if child["is_group"]:
                directories.append(relative.as_posix())
                children(child["id"], relative)
            else:
                target = Path(child["path"]) / ".context/notes"
                if target.is_dir():
                    mounts[relative.as_posix()] = {
                        "id": child["id"], "context": child["breadcrumb"],
                        "target": os.path.relpath(target, vault / relative.parent),
                    }

    children(node["id"])
    descendants(node["id"])
    return vault, {"version": 1, "id": node["id"], "context": node["breadcrumb"],
                   "mounts": mounts, "directories": directories, "labels": labels}


def board(vault, value):
    """Extend existing board without replacing user views or presentation settings."""
    path = vault / "Kanban.base"
    if not path.exists():
        return
    data = yaml.safe_load(notebook.read(path))
    if not isinstance(data, dict) or not isinstance(data.get("views"), list):
        raise ctl.ContextError(f"Invalid Kanban board: {path}")
    original = copy.deepcopy(data)
    # Deepest mount first; ordinary subfolders retain their owning context label.
    expression = json.dumps(value["context"], ensure_ascii=False)
    for name, label in sorted(value["labels"].items(), key=lambda pair: pair[0].count("/")):
        expression = f'if(file.inFolder({json.dumps(name)}), {json.dumps(label, ensure_ascii=False)}, {expression})'
    data.setdefault("formulas", {})["Context"] = expression
    data.setdefault("properties", {})["formula.Context"] = {"displayName": "Context"}
    filters = data.setdefault("filters", {"and": []})
    if isinstance(filters, dict) and isinstance(filters.get("and"), list):
        for folder in ("Templates", "Attachments"):
            check = f'!file.path.split("/").contains("{folder}")'
            if check not in filters["and"]:
                filters["and"].append(check)
    for view in data["views"]:
        if view.get("type") == "kanban":
            order = view.setdefault("order", ["file.name"])
            if "formula.Context" not in order:
                order.append("formula.Context")
    local = next((view for view in data["views"] if view.get("name") == "This context"), None)
    if local is None:
        source = next((view for view in data["views"] if view.get("type") == "kanban"), None)
        if source:
            local = copy.deepcopy(source)
            local["name"] = "This context"
            data["views"].append(local)
    if local is not None:
        local["filters"] = {"and": [f'!file.inFolder({json.dumps(name)})'
                                     for name in value["mounts"]]}
    if data != original:
        notebook.write(path, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def reconcile(nodes):
    """Caller serializes hierarchy mutations; watcher also retries incoming changes."""
    plans = [plan(nodes, node) for node in nodes if not node["is_group"]]
    global_node = {"id": GLOBAL_ID, "path": str(ctl.root()), "breadcrumb": "All contexts"}
    global_vault = ctl.root() / ".context/notes"
    notebook.setup(global_vault)
    global_nodes = [node | {"parent_id": node["parent_id"] or GLOBAL_ID} for node in nodes]
    plans.append(plan(global_nodes, global_node))
    errors, valid = [], []
    # Remove stale edges everywhere before adding any: a reparent must not create
    # a transient link cycle through a former ancestor's still-mounted notebook.
    for vault, desired in plans:
        try:
            old = manifest(vault)
            for name, mount in old.get("mounts", {}).items():
                path = local_path(vault, name)
                replacement = desired["mounts"].get(name)
                if ((replacement is None or any(replacement[key] != mount[key] for key in ("id", "target")))
                        and path.is_symlink()
                        and os.readlink(path) == mount["target"]):
                    path.unlink()
            for name in sorted(old.get("directories", []), key=lambda name: name.count("/"), reverse=True):
                if name not in desired["directories"]:
                    path = local_path(vault, name)
                    if path.is_dir() and not path.is_symlink():
                        try:
                            path.rmdir()
                        except OSError:
                            pass  # User contents are never removed.
            valid.append((vault, desired))
        except (OSError, ValueError, ctl.ContextError) as exc:
            errors.append(f"{desired['context']}: {exc}")
    for vault, desired in valid:
        try:
            old = manifest(vault)
            # Validate collisions before creating anything. Existing ordinary
            # folders are user-owned unless our previous manifest created them.
            for name in desired["directories"]:
                path = local_path(vault, name)
                if path.is_symlink() or (path.exists() and name not in old.get("directories", [])):
                    raise ctl.ContextError(f"Notebook folder collision: {path}")
            for name, mount in desired["mounts"].items():
                path = local_path(vault, name)
                if path.is_symlink() and os.readlink(path) == mount["target"]:
                    continue
                if path.exists() or path.is_symlink():
                    raise ctl.ContextError(f"Notebook folder collision; preserve existing entry: {path}")
            target = vault / MANIFEST
            # Record intent first so interrupted creation is recoverable.
            if old != desired:
                ctl.atomic_json(target, desired)
            for name in desired["directories"]:
                local_path(vault, name).mkdir(exist_ok=True)
            for name, mount in desired["mounts"].items():
                path = local_path(vault, name)
                if not path.is_symlink():
                    path.symlink_to(mount["target"], target_is_directory=True)
            board(vault, desired)
        except (OSError, ValueError, ctl.ContextError, yaml.YAMLError) as exc:
            errors.append(f"{desired['context']}: {exc}")
    return errors


def owner(vault, identifier, name):
    """Resolve only generated child mounts, validating stable owner and target."""
    relative = ctl.relative_name(name)
    value = manifest(vault)
    for prefix, mount in value.get("mounts", {}).items():
        if relative == Path(prefix) or not relative.is_relative_to(prefix):
            continue
        path = local_path(vault, prefix)
        child = ctl.selected_context(mount["id"])
        if child is None:
            raise ctl.ContextError("Child notebook is unavailable")
        target = Path(child["path"]) / ".context/notes"
        # Recheck current hierarchy, not merely an old manifest left by a move.
        import organization
        nodes = {node["id"]: node for node in organization.resolve(ctl.known_contexts())}
        chain = [*nodes[mount["id"]]["ancestors"], mount["id"]]
        if identifier != GLOBAL_ID and identifier not in chain[:-1]:
            raise ctl.ContextError("Child notebook moved; refresh the parent notebook")
        visible = chain if identifier == GLOBAL_ID else chain[chain.index(identifier) + 1:]
        if Path(*(nodes[key]["label"] for key in visible)) != Path(prefix):
            raise ctl.ContextError("Child notebook moved or renamed; refresh the parent notebook")
        if not path.is_symlink() or path.resolve() != target.resolve():
            raise ctl.ContextError("Child notebook link changed; wait for reconciliation")
        return target, mount["id"], mount["context"], relative.relative_to(prefix).as_posix()
    return Path(vault), identifier, value.get("context", identifier), relative.as_posix()
