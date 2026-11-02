"""Explicit tab closure: durable forgetting, private capture, then teardown.

No whole-context checkpoint or chat-library sweep belongs on this path. Local
closure records take effect before staging; additive portable records prevent an
older checkpoint from resurrecting deliberately closed tabs on another machine.
"""

import copy
import os
from pathlib import Path
import time
import uuid

import contextctl as ctl


STAGING = "__context_closing_"


def target_context(tm, session, name, explicit, panes):
    """Read only this session's owning metadata; never walk other contexts."""
    import persistence as p

    try:
        environment = tm.call("show-environment", "-t", session, "CONTEXT_DIRECTORY")
        directory = Path(environment.split("=", 1)[1]) if environment.startswith("CONTEXT_DIRECTORY=") else None
    except p.CheckpointError:
        directory = None
    expected = explicit or (name[8:] if name.startswith("context-") else None)
    if not expected:
        directory = None  # An inherited environment is not ownership proof.
        if panes is None:
            panes = tm.rows("list-panes", ["pane_current_path"], "-s", "-t", session)
    if directory is None and not expected:
        # Unregistered shells can belong to a context by their local cwd. Only
        # examine ancestors within the local context root, never external paths.
        candidates = set()
        root = ctl.root().absolute()
        for row in panes:
            path = Path(row["pane_current_path"]).absolute()
            if not path.is_relative_to(root):
                return None
            found = next((ancestor for ancestor in (path, *path.parents)
                          if ancestor != root and ancestor.is_relative_to(root)
                          and (ancestor / ".context/context.json").is_file()), None)
            if found is None:
                return None
            candidates.add(found)
        if len(candidates) == 1:
            directory = candidates.pop()
    if directory is None:
        if expected:
            raise p.CheckpointError("Context session lacks CONTEXT_DIRECTORY; refresh its ownership before closing")
        return None
    directory = ctl.contained(ctl.root(), directory.absolute())
    data = ctl.read_json(directory / ".context/context.json", {})
    if not data:  # Removed context: use the existing machine-local orphan policy.
        return None
    if data.get("version") != 1 or str(uuid.UUID(data["id"])) != data["id"] or (expected and data["id"] != expected):
        raise p.CheckpointError("Context ownership changed; tab left intact")
    work = ctl.working_path(directory, data["working_directory"])
    return {"id": data["id"], "name": directory.relative_to(ctl.root()).as_posix(),
            "path": str(directory), "cwd": str(work), "working_directory": data["working_directory"],
            "working_directory_path": str(work), "working_directory_available": None}


def durable_record(path, value):
    ctl.atomic_json(path, value)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def record_roots(context):
    import persistence as p

    key = context["id"] if context else "local"
    return (p.local_root() / "closures" / key,
            p.state_dir(context) / "terminal" / "closed")


def closed_ids(context):
    result = set()
    for root in record_roots(context):
        for path in root.glob("*.json"):
            value = ctl.read_json(path)
            if value.get("version") != 1 or value.get("pane") != path.stem:
                raise ctl.ContextError(f"Invalid tab closure record: {path}")
            uuid.UUID(value["pane"])
            result.add(value["pane"])
    return result


def filter_closed(sessions, context):
    """Filter even stale snapshots and legacy retained entries before restore."""
    removed = closed_ids(context)
    result = copy.deepcopy(sessions)
    for session in result:
        for window in session["windows"]:
            old = window["panes"]
            window["panes"] = [p for p in old if p["id"] not in removed]
            if window["panes"] and len(old) != len(window["panes"]):
                # A stale layout still contains deleted leaves. Use a coherent
                # recovery layout until the next live observation replaces it.
                width, height = map(int, window["layout"].split(",")[1].split("x"))
                height = max(height, 3 * len(window["panes"]))
                available, y, leaves = height - len(window["panes"]) + 1, 0, []
                for index, pane in enumerate(window["panes"]):
                    size = available // (len(window["panes"]) - index)
                    leaves.append(f"{width}x{size},0,{y},{pane['observed_id'].lstrip('%')}")
                    y += size + 1
                    available -= size
                body = leaves[0] if len(leaves) == 1 else f"{width}x{height},0,0[" + ",".join(leaves) + "]"
                window["layout"] = "0000," + body
            if window["panes"] and not any(p["active"] for p in window["panes"]):
                window["panes"][0]["active"] = True
        session["windows"] = [w for w in session["windows"] if w["panes"]]
        if session["windows"] and not any(w["active"] for w in session["windows"]):
            session["windows"][0]["active"] = True
    return [s for s in result if s["windows"] and not s["name"].startswith(STAGING)]


def close_tab(socket_path, operation, target_session, target_window, target_pane=None, all_targets=False):
    import persistence as p

    tm = p.Tmux(socket_path)
    session = target_session.removeprefix("x")
    window = target_window.removeprefix("x")
    pane = target_pane.removeprefix("x") if target_pane else None
    # Duplicates must not race a move or capture the same editor twice. Other
    # windows have independent slots even when one exporter is slow.
    with ctl.runtime_operation("tab-close:" + socket_path + ":" + window):
        rows = tm.rows("list-sessions", ["session_id", "session_name", "@persistence-context"],
                       "-f", "#{==:#{session_id}," + session + "}")
        if not rows:
            return
        source = rows[0]
        if source["session_name"].startswith(STAGING):
            raise p.CheckpointError("Recovery staging must be retried, not closed as a normal tab")
        fields = ["pane_id", "window_id", "pane_index", "pane_pid", "pane_current_path",
                  "pane_current_command", "pane_title", "@persistence-editor",
                  "@persistence-editor-socket", "@persistence-chat-socket"]
        rows = tm.rows("list-panes", fields, "-s", "-t", session)
        if operation == "kill-window":
            selected = [r for r in rows if (r["window_id"] != window if all_targets else r["window_id"] == window)]
            # Match native kill-window -a semantics for duplicate links.
            if all_targets:
                links = tm.rows("list-windows", ["window_id"], "-t", session)
                if sum(r["window_id"] == window for r in links) > 1:
                    selected = rows
        elif operation == "kill-pane":
            selected = [r for r in rows if r["window_id"] == window and
                        (r["pane_id"] != pane if all_targets else r["pane_id"] == pane)]
        else:
            raise p.CheckpointError("Tab close only accepts kill-window or kill-pane")
        if not selected:
            return
        context = target_context(tm, session, source["session_name"], source.get("@persistence-context"), rows)
        related_contexts = {context["id"] if context else None: context}
        local, _ = record_roots(context)
        request = uuid.uuid4().hex
        recovery = p.local_root() / "closed-work" / request
        recovery.mkdir(parents=True, mode=0o700)
        documents = []
        seen = set()
        for row in selected:
            if row["pane_id"] in seen:
                continue
            seen.add(row["pane_id"])
            identity = tm.identity(row["pane_id"], ("-p",))
            document = {"version": 1, "pane": identity, "request": request, "created_ns": time.time_ns()}
            durable_record(local / (identity + ".json"), document)
            documents.append(document)
            row["stable_id"] = identity
        selected = [r for index, r in enumerate(selected) if r["pane_id"] not in {x["pane_id"] for x in selected[:index]}]
        # Persist recovery intent before removing any visible link. This record
        # names only requested panes, and remains usable after helper interruption.
        durable_record(recovery / "request.json", {"socket": socket_path, "session": session,
                        "operation": operation, "panes": selected, "context": context, "status": "staging"})
        staging = STAGING + request
        dummy = tm.call("new-session", "-d", "-P", "-F", "#{pane_id}", "-s", staging,
                        "-c", str(Path.home()), "/bin/sh")
        tm.call("set-option", "-t", staging, "@persistence-close-staging", "1")
        tm.call("set-option", "-w", "-t", dummy, "@persistence-close-staged", "1")
        moved = set()
        affected = {session}
        for row in selected:
            if operation == "kill-window" or sum(r["window_id"] == row["window_id"] for r in rows) == 1:
                if row["window_id"] in moved:
                    continue
                # Mark before moving; native final teardown never starts another
                # archive. Grouped/linked windows are inherently related targets.
                tm.call("set-option", "-w", "-t", row["window_id"], "@persistence-close-staged", "1")
                linked = tm.call("display-message", "-p", "-t", row["pane_id"], "#{window_linked}") == "1"
                links = tm.rows("list-windows", ["session_id", "session_name", "window_id", "window_index", "@persistence-context"], "-a") if linked else []
                for link in links:
                    if link["window_id"] != row["window_id"]:
                        continue
                    related = target_context(tm, link["session_id"], link["session_name"], link["@persistence-context"], None)
                    related_contexts[related["id"] if related else None] = related
                    for document in documents:
                        durable_record(record_roots(related)[0] / (document["pane"] + ".json"), document)
                tm.call("move-window", "-d", "-s", session + ":" + row["window_id"], "-t", staging + ":")
                related = {link["session_id"] for link in links if link["window_id"] == row["window_id"]}
                affected.update(related)
                for identifier in related:
                    try:
                        remaining = tm.rows("list-windows", ["window_id", "window_index"], "-t", identifier)
                    except p.CheckpointError as exc:
                        if "can't find session" in str(exc) or "no such session" in str(exc):
                            continue
                        raise
                    for link in remaining:
                        if link["window_id"] == row["window_id"]:
                            tm.call("unlink-window", "-k", "-t", identifier + ":" + row["window_id"])
                moved.add(row["window_id"])
            else:
                target = tm.call("break-pane", "-d", "-P", "-F", "#{window_id}",
                                 "-s", row["pane_id"], "-t", staging + ":")
                tm.call("set-option", "-w", "-t", target, "@persistence-close-staged", "1")
        # Moving a window to recovery skips native kill-window renumbering.
        # Compact surviving source sessions before any slow capture, respecting
        # each session's option and allowing the final source session to vanish.
        for identifier in affected:
            survivors = tm.rows("list-sessions", ["session_id"], "-f",
                                "#{&&:#{==:#{session_id}," + identifier + "},#{renumber-windows}}")
            if survivors:
                tm.call("move-window", "-r", "-t", identifier + ":")
        durable_record(recovery / "request.json", {"socket": socket_path, "window": window,
                        "panes": selected, "context": context, "dummy": dummy,
                        "related_contexts": list(related_contexts.values())})
        finish_close(tm, selected, context, recovery, staging, dummy, documents, list(related_contexts.values()))


def finish_close(tm, selected, context, recovery, staging, dummy, documents, related_contexts):
    import persistence as p

    def check_targets():
        actual = tm.rows("list-panes", ["pane_id", "pane_pid", "@persistence-id", "pane_current_command"], "-s", "-t", staging)
        if {r["pane_id"] for r in actual} != {dummy, *(r["pane_id"] for r in selected)}:
            raise p.CheckpointError("Closing tab changed during staging/capture; processes kept alive")
        for row in selected:
            current = next(r for r in actual if r["pane_id"] == row["pane_id"])
            if (current["pane_pid"] != row["pane_pid"] or current["@persistence-id"] != row["stable_id"]
                    or current["pane_current_command"] != row["pane_current_command"]):
                raise p.CheckpointError("Closing pane identity changed; processes kept alive")

    # User already has control and requested tabs are gone. Only now perform
    # exporter RPCs and portable writes. Failures leave private processes alive.
    try:
        check_targets()
        for row in selected:
            if row["pane_current_command"] not in ("nvim", "opencode", "bun") and not row["@persistence-chat-socket"]:
                continue
            value = {"id": row["stable_id"], "command": row["pane_current_command"],
                     "cwd": p.encode_path(row["pane_current_path"], context), "local": dict(row)}
            tree = p.store.Tree()
            warnings = []
            p.adapter_capture(tm, value, tree.path(), context, warnings)
            destination = recovery / row["stable_id"]
            for name, content in tree.files.items():
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with path.open("wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
            durable_record(destination / "recovery.json", value)
        for related in related_contexts:
            for document in documents:
                durable_record(record_roots(related)[1] / (document["pane"] + ".json"), document)
        check_targets()
        tm.call("kill-session", "-t", staging)
        durable_record(recovery / "status.json", {"status": "saved", "staging": staging})
    except Exception as exc:
        durable_record(recovery / "status.json", {"status": "failed", "staging": staging, "error": str(exc)})
        raise p.CheckpointError(f"Tab close recovery kept in {staging}: {exc}. Retry: context-checkpoint retry-close --request {recovery.name}") from exc


def retry_close(request):
    import persistence as p

    if not request or uuid.UUID(hex=request).hex != request:
        raise p.CheckpointError("Invalid close request")
    recovery = p.local_root() / "closed-work" / request
    value = ctl.read_json(recovery / "request.json")
    if "dummy" not in value:
        raise p.CheckpointError(f"Staging incomplete; recover processes manually in {STAGING + request}")
    with ctl.runtime_operation("tab-close:" + value["socket"] + ":" + value["window"]):
        documents = [ctl.read_json(record_roots(value["context"])[0] / (r["stable_id"] + ".json")) for r in value["panes"]]
        finish_close(p.Tmux(value["socket"]), value["panes"], value["context"], recovery,
                     STAGING + request, value["dummy"], documents, value["related_contexts"])
