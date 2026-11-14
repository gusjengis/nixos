#!/usr/bin/env python3
"""Route desktop URL opens through the current context, never global browser MRU."""

import fcntl
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import contextctl as contexts


BROWSER_CLASSES = {"chromium", "chromium-browser"}


def select_browser(snapshot, clients):
    current = next((item for item in snapshot["sessions"]
                    if item["id"] == snapshot["active"]), None)
    if not current or current.get("closing"):
        raise contexts.ContextError("Current context is missing or closing")
    owned = set(current["windows"])
    browsers = [client for client in clients
                if client.get("address") in owned
                and client.get("class", "").lower() in BROWSER_CLASSES
                and client.get("mapped", True)]

    def recency(client):
        rank = client.get("focusHistoryID", -1)
        return rank if isinstance(rank, int) and rank >= 0 else float("inf")

    return min(browsers, key=recency) if browsers else None


def guarded(statement, runtime_id):
    return ("local s=require('sessions'); assert(s.state().active=="
            + contexts.lua_string(runtime_id) + ", 'Active context changed'); " + statement)


def open_links(urls):
    browser = str(Path.home() / ".nix-profile/bin/chromium")
    # Ordinary desktops (including contexts-disabled hosts) keep ordinary behavior.
    # A present but unreadable/broken context snapshot must NOT fall back globally.
    if os.environ.get("CONTEXT_BROWSER_ENABLED") == "0":
        subprocess.Popen([browser, *urls], start_new_session=True)
        return
    path = contexts.runtime_path("hyprland-sessions")

    # Serialize rapid clicks through focus delivery and the singleton handoff.
    with path.with_suffix(".browser.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        snapshot = contexts.read_json(path)
        runtime_id = snapshot["active"]
        target = select_browser(snapshot, contexts.clients())
        arguments = [browser, "--new-tab" if target else "--new-window", "--", *urls]
        if target:
            # The selected window may belong to a separately running browser profile.
            profile = contexts.process_profile(target.get("pid"))
            if profile:
                arguments.insert(1, "--user-data-dir=" + profile)
        # A launch token inherited from the source app is not browser ownership.
        command = shlex.join(["env", "-u", "XDG_ACTIVATION_TOKEN", "-u", "DESKTOP_STARTUP_ID", *arguments])
        if target:
            address = contexts.lua_string(target["address"])
            membership = ("local owned=false; for _,item in ipairs(s.state().sessions) do "
                          "if item.id==s.state().active then for _,a in ipairs(item.windows) do "
                          "if a==" + address + " then owned=true end end end end; "
                          "assert(owned, 'Browser left current context'); ")
            contexts.evaluate(guarded(membership + "s.focus_window("
                                      + contexts.lua_string("address:" + target["address"]) + ")", runtime_id))
            if not urls:
                return
            # Wayland focus is asynchronous. Let Chromium update its own MRU before
            # sending the URL to its singleton process; then recheck focus/ownership.
            time.sleep(0.15)
            contexts.evaluate(guarded(
                membership + "local w=hl.get_active_window(); assert(w and w.address=="
                + address + ", 'Browser focus changed'); hl.exec_cmd(" + contexts.lua_string(command) + ")",
                runtime_id))
        else:
            workspace = f"special:session-{runtime_id}-browser"
            contexts.evaluate(guarded(
                "s.launch_special('browser'," + contexts.lua_string(command) + ","
                + contexts.lua_string(workspace) + "); s.show_special('browser')", runtime_id))
        # Keep a second click from overtaking the browser's singleton handoff.
        time.sleep(0.15)


def main(argv=None):
    try:
        open_links(sys.argv[1:] if argv is None else argv)
    except (contexts.ContextError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(f"context-browser: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
