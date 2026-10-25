"""Opt-in native Obsidian acceptance, isolated profile/vault and headless display."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

import context_notes
import contextctl as ctl
import notebook


@unittest.skipUnless(os.environ.get("NOTEBOOK_NATIVE_TESTS") == "1", "opt-in native Obsidian fixture")
class NativeNotebookTests(unittest.TestCase):
    def test_board_creation_move_reentry_and_reopen(self):
        from websockets.sync.client import connect

        with tempfile.TemporaryDirectory(prefix="notebook-native-", dir="/tmp/opencode") as directory:
            base = Path(directory)
            vault, profile = base / "vault", base / "profile"
            vault.mkdir()
            notebook.setup(vault)
            vault_id = "1234567890abcdef"
            profile.mkdir()
            ctl.atomic_json(profile / "obsidian.json", {"vaults": {vault_id: {"path": str(vault), "open": True}}})
            notebook.enable_profile(profile, vault_id)
            # Optional installed application update, without modifying the real profile.
            if asar := os.environ.get("OBSIDIAN_TEST_ASAR"):
                shutil.copyfile(asar, profile / Path(asar).name)

            def launch():
                log = (base / "obsidian.log").open("a")
                self.addCleanup(log.close)
                process = subprocess.Popen([
                    os.environ.get("OBSIDIAN_TEST_BINARY", "obsidian"), f"--user-data-dir={profile}", "--disable-gpu",
                    "--ozone-platform=headless", "--remote-debugging-port=0",
                    "--remote-allow-origins=*",
                ], stdin=subprocess.DEVNULL, stdout=log, stderr=log)
                self.addCleanup(lambda: process.poll() is None and process.terminate())
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail((base / "obsidian.log").read_text())
                    try:
                        port = (profile / "DevToolsActivePort").read_text().splitlines()[0]
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
                            targets = json.load(response)
                        page = next(target for target in targets if target.get("type") == "page" and "index.html" in target.get("url", ""))
                        socket = connect(page["webSocketDebuggerUrl"], open_timeout=2)
                        socket.send(json.dumps({"id": -1, "method": "Runtime.enable"}))
                        socket.send(json.dumps({"id": -2, "method": "Emulation.setDeviceMetricsOverride", "params": {
                            "width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False,
                        }}))
                        return process, socket
                    except (OSError, StopIteration, TimeoutError):
                        time.sleep(.2)
                self.fail("Obsidian startup timed out:\n" + (base / "obsidian.log").read_text())

            sequence = 0

            def evaluate(socket, expression):
                nonlocal sequence
                sequence += 1
                socket.send(json.dumps({"id": sequence, "method": "Runtime.evaluate", "params": {
                    "expression": expression, "awaitPromise": True, "returnByValue": True,
                }}))
                while True:
                    reply = json.loads(socket.recv(timeout=20))
                    if reply.get("method") == "Runtime.exceptionThrown":
                        print("NATIVE EXCEPTION", reply)
                    if reply.get("id") != sequence:
                        continue
                    self.assertNotIn("error", reply)
                    result = reply["result"]
                    self.assertNotIn("exceptionDetails", result, result)
                    return result["result"].get("value")

            def wait(socket, expression):
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if evaluate(socket, expression):
                        return
                    time.sleep(.2)
                diagnostic = evaluate(socket, "JSON.stringify({active:app.workspace.getActiveFile()?.path,columns:document.querySelectorAll('.bases-kanban-column').length,headings:Array.from(document.querySelectorAll('.bases-kanban-column .bases-group-value')).map(e=>e.textContent),errors:Array.from(document.querySelectorAll('.bases-error')).map(e=>e.textContent),text:document.body.innerText.slice(-2000),dimensions:[innerWidth,innerHeight],view:Object.fromEntries(Object.entries(app.workspace.getMostRecentLeaf().view).map(([key,value])=>[key,value&&typeof value==='object'?Object.keys(value).slice(0,30):typeof value]))})")
                self.fail("Native condition timed out: " + expression + "\n" + diagnostic + "\n" + (base / "obsidian.log").read_text())

            process, socket = launch()
            try:
                wait(socket, "!!window.app?.plugins?.plugins?.['context-notebook']")
                wait(socket, "app.workspace.getActiveFile()?.path === 'Kanban.base'")
                evaluate(socket, "app.vault.create('Acceptance.md', 'Dictated body stays intact.\\n').then(()=>true)")
                wait(socket, "app.metadataCache.getCache('Acceptance.md')?.frontmatter?.status === 'Thoughts'")
                # Native rendering creates one extra hidden sizing column.
                wait(socket, "Array.from(document.querySelectorAll('.bases-kanban-column .bases-group-value')).filter(e=>e.textContent!=='Fj').length === 4")
                headings = evaluate(socket, "Array.from(document.querySelectorAll('.bases-kanban-column .bases-group-value')).map(e=>e.textContent).filter(text=>text!=='Fj')")
                self.assertEqual(headings, list(notebook.PHASES))
                initial = evaluate(socket, "app.metadataCache.getCache('Acceptance.md').frontmatter")
                self.assertEqual(initial["kanban-history"][0]["event"], "entered")
                # Call the native Kanban move operation used by its drop handler.
                for phase in ("Todo", "In-Progress", "Todo", "Done"):
                    result = evaluate(socket, """(async () => {
                        const leaf = app.workspace.getMostRecentLeaf();
                        const view = leaf.view;
                        const find = object => {
                            if (!object || typeof object !== 'object') return null;
                            if (typeof object.moveCardToColumn === 'function') return object;
                            return null;
                        };
                        const board = find(view) || Object.values(view).map(find).find(Boolean)
                            || Object.values(view).flatMap(value => value && typeof value === 'object' ? Object.values(value) : []).map(find).find(Boolean);
                        if (!board) return {keys: Object.keys(view), missing: true};
                        const target = board.orderedGroups.find(group => group.key?.toString() === PHASE);
                        await board.moveCardToColumn(app.vault.getAbstractFileByPath('Acceptance.md'), target.key);
                        return {moved: true};
                    })()""".replace("PHASE", json.dumps(phase)))
                    self.assertEqual(result, {"moved": True})
                    wait(socket, "app.metadataCache.getCache('Acceptance.md')?.frontmatter?.['kanban-history']?.at(-1)?.status === " + json.dumps(phase))
                final = evaluate(socket, "app.metadataCache.getCache('Acceptance.md').frontmatter")
                self.assertEqual([event["status"] for event in final["kanban-history"]], ["Thoughts", "Todo", "In-Progress", "Todo", "Done"])
                self.assertEqual(initial["created"], final["created"])
                self.assertTrue((vault / "Acceptance.md").read_text().endswith("Dictated body stays intact.\n"))
                api = context_notes.Vault(vault, "native-fixture")
                card = api.read({"path": "Acceptance.md"})
                with patch.object(ctl, "state_root", return_value=base / "state"):
                    api.update({"path": card["path"], "revision": card["revision"], "status": "Todo",
                                "work_state": "Next: native acceptance with the notebook open."})
                wait(socket, "app.metadataCache.getCache('Acceptance.md')?.frontmatter?.['kanban-history']?.at(-1)?.status === 'Todo'")
                time.sleep(.3)
                final = evaluate(socket, "app.metadataCache.getCache('Acceptance.md').frontmatter")
                self.assertEqual([event["status"] for event in final["kanban-history"]],
                                 ["Thoughts", "Todo", "In-Progress", "Todo", "Done", "Todo"])
                evaluate(socket, "app.workspace.getLeaf(false).openFile(app.vault.getAbstractFileByPath('Acceptance.md'))")
                wait(socket, "app.workspace.getActiveFile()?.path === 'Acceptance.md'")
                evaluate(socket, "app.workspace.saveLayout()")
                time.sleep(1)
                process.terminate()
                process.wait(timeout=10)
            finally:
                socket.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)
            (profile / "DevToolsActivePort").unlink(missing_ok=True)
            # An agent can update phase/history with Obsidian closed. On reopening,
            # the Obsidian plugin must not append a duplicate transition.
            api = context_notes.Vault(vault, "native-fixture")
            card = api.read({"path": "Acceptance.md"})
            with patch.object(ctl, "state_root", return_value=base / "state"):
                card = api.update({"path": card["path"], "revision": card["revision"],
                                   "status": "In-Progress", "work_state": "Next: finish native acceptance."})
            _, final, _ = notebook.fields(card["content"])
            process, socket = launch()
            try:
                wait(socket, "!!window.app?.plugins?.plugins?.['context-notebook']")
                wait(socket, "app.workspace.getActiveFile()?.path === 'Kanban.base'")
                wait(socket, "!!app.metadataCache.getCache('Acceptance.md')?.frontmatter?.['kanban-history']")
                reopened = evaluate(socket, "app.metadataCache.getCache('Acceptance.md').frontmatter")
                self.assertEqual(reopened["kanban-history"], final["kanban-history"])
            finally:
                socket.close()
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
