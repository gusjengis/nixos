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
import notebook_hierarchy
import organization
import yaml


@unittest.skipUnless(os.environ.get("NOTEBOOK_NATIVE_TESTS") == "1", "opt-in native Obsidian fixture")
class NativeNotebookTests(unittest.TestCase):
    def test_board_creation_move_reentry_and_reopen(self):
        from websockets.sync.client import connect

        with tempfile.TemporaryDirectory(prefix="notebook-native-", dir="/tmp/opencode") as directory:
            base = Path(directory)
            fixture_environment = patch.dict(os.environ, {
                "CONTEXT_ROOT": str(base / "contexts"), "XDG_STATE_HOME": str(base / "state"),
            })
            fixture_environment.start()
            self.addCleanup(fixture_environment.stop)
            parent_context = ctl.create("Parent")
            child_context = ctl.create("Child")
            grandchild_context = ctl.create("Grandchild")
            identifier = parent_context["id"]
            vault = ctl.root() / "Parent/.context/notes"
            child = ctl.root() / "Child/.context/notes"
            grandchild = ctl.root() / "Grandchild/.context/notes"
            profile = base / "obsidian" / identifier
            organization.change([child_context["id"]], parent=identifier)
            organization.change([grandchild_context["id"]], parent=child_context["id"])
            (grandchild / "Nested.md").write_text("---\nstatus: Todo\n---\nGrandchild body.\n")
            (grandchild / "Templates").mkdir()
            (grandchild / "Templates/Hidden.md").write_text("Template, not a card.")
            (grandchild / "Assets").mkdir()
            (grandchild / "Assets/reference.txt").write_text("Attached reference.")
            (grandchild / "Linked.md").write_text("[[Nested]]\n[Reference](Assets/reference.txt)\n")
            self.assertEqual(ctl.reconcile_notebooks(), [])
            local_board = yaml.safe_load((vault / "Kanban.base").read_text())
            local_board["views"] = [next(view for view in local_board["views"] if view["name"] == "This context")]
            notebook.write(vault / "Local acceptance.base", yaml.safe_dump(local_board))
            (vault / "Parent only.md").write_text("---\nstatus: Todo\n---\nLocal note.\n")
            vault_id = "1234567890abcdef"
            profile.mkdir(parents=True)
            ctl.atomic_json(profile / "obsidian.json", {"vaults": {vault_id: {"path": str(vault), "open": True}}})
            notebook.enable_profile(profile, vault_id)
            # Never let native fixtures unlink the desktop's shared CLI socket.
            runtime = base / "r"
            runtime.mkdir(mode=0o700)
            with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
                environment = ctl.obsidian_environment(identifier)
            # Optional installed application update, without modifying the real profile.
            if asar := os.environ.get("OBSIDIAN_TEST_ASAR"):
                shutil.copyfile(asar, profile / Path(asar).name)

            def launch(profile=profile, environment=environment, log_name="obsidian.log"):
                log = (base / log_name).open("a")
                self.addCleanup(log.close)
                process = subprocess.Popen([
                    os.environ.get("OBSIDIAN_TEST_BINARY", "obsidian"), f"--user-data-dir={profile}", "--disable-gpu",
                    "--ozone-platform=headless", "--remote-debugging-port=0",
                    "--remote-allow-origins=*",
                ], stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=environment)
                def cleanup():
                    if process.poll() is None:
                        process.terminate()
                        process.wait(timeout=10)
                self.addCleanup(cleanup)
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail((base / log_name).read_text())
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
                self.fail("Obsidian startup timed out:\n" + (base / log_name).read_text())

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
                wait(socket, "!!app.vault.getAbstractFileByPath('Child/Grandchild/Nested.md')")
                wait(socket, "document.body.innerText.includes('Nested')")
                wait(socket, "document.body.innerText.includes('Parent / Child / Grandchild')")
                self.assertFalse(evaluate(socket, "document.body.innerText.includes('Hidden')"))
                evaluate(socket, "app.workspace.getLeaf(false).openFile(app.vault.getAbstractFileByPath('Local acceptance.base')).then(()=>true)")
                wait(socket, "app.workspace.getMostRecentLeaf().view.contentEl.innerText.includes('Parent only')")
                self.assertFalse(evaluate(socket, "app.workspace.getMostRecentLeaf().view.contentEl.innerText.includes('Nested')"))
                evaluate(socket, "app.workspace.getLeaf(false).openFile(app.vault.getAbstractFileByPath('Kanban.base')).then(()=>true)")
                wait(socket, "document.body.innerText.includes('Nested')")
                # A second profile must neither steal routing nor remove the
                # first profile's command socket when it exits (Obsidian 1.14.5).
                other_id = grandchild_context["id"]
                other_profile = base / "obsidian" / other_id
                other_profile.mkdir()
                other_vault = grandchild
                ctl.atomic_json(other_profile / "obsidian.json", {"vaults": {
                    "fedcba0987654321": {"path": str(other_vault), "open": True},
                }})
                notebook.enable_profile(other_profile, "fedcba0987654321")
                if asar := os.environ.get("OBSIDIAN_TEST_ASAR"):
                    shutil.copyfile(asar, other_profile / Path(asar).name)
                with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
                    other_environment = ctl.obsidian_environment(other_id)
                other_process, other_connection = launch(other_profile, other_environment, "other.log")
                self.addCleanup(other_connection.close)
                wait(other_connection, "!!window.app?.plugins?.plugins?.['context-notebook']")
                wait(other_connection, "app.metadataCache.getCache('Nested.md')?.frontmatter?.['kanban-history']?.length === 1")
                nested_path = "Child/Grandchild/Nested.md"
                wait(socket, "app.metadataCache.getCache('Child/Grandchild/Nested.md')?.frontmatter?.['kanban-history']?.length === 1")
                # Two open vaults observe one transition on the same physical note.
                evaluate(socket, "app.fileManager.processFrontMatter(app.vault.getAbstractFileByPath('Child/Grandchild/Nested.md'), f => { f.status = 'In-Progress'; }).then(()=>true)")
                for connection, path in ((socket, nested_path), (other_connection, "Nested.md")):
                    wait(connection, "app.metadataCache.getCache(" + json.dumps(path) + ")?.frontmatter?.['kanban-history']?.at(-1)?.status === 'In-Progress'")
                    self.assertEqual(evaluate(connection, "app.metadataCache.getCache(" + json.dumps(path) + ").frontmatter['kanban-history'].map(e=>e.status)"), ["Todo", "In-Progress"])
                # Agent atomic replacement is noticed through both levels of links.
                api = context_notes.resolve(identifier)
                card = api.read({"path": nested_path})
                api.update({"path": nested_path, "revision": card["revision"], "status": "Done"})
                wait(socket, "app.metadataCache.getCache('Child/Grandchild/Nested.md')?.frontmatter?.status === 'Done'")
                wait(other_connection, "app.metadataCache.getCache('Nested.md')?.frontmatter?.status === 'Done'")
                self.assertTrue((child / "Grandchild").is_symlink())
                self.assertEqual(evaluate(socket, "app.metadataCache.getFirstLinkpathDest('Nested', 'Child/Grandchild/Linked.md')?.path"), nested_path)
                self.assertEqual(evaluate(socket, "app.metadataCache.getFirstLinkpathDest('Assets/reference.txt', 'Child/Grandchild/Linked.md')?.path"), "Child/Grandchild/Assets/reference.txt")
                # Reconcile while Obsidian is live: no restart needed to discover
                # renamed, moved or newly created notebook folders and labels.
                organization.change([child_context["id"]], new_label="Renamed child")
                self.assertEqual(ctl.reconcile_notebooks(), [])
                wait(socket, "!!app.vault.getAbstractFileByPath('Renamed child/Grandchild/Nested.md') && !app.vault.getAbstractFileByPath('Child/Grandchild/Nested.md')")
                wait(socket, "document.body.innerText.includes('Parent / Renamed child / Grandchild')")
                organization.change([grandchild_context["id"]], parent=identifier)
                self.assertEqual(ctl.reconcile_notebooks(), [])
                wait(socket, "!!app.vault.getAbstractFileByPath('Grandchild/Nested.md') && !app.vault.getAbstractFileByPath('Renamed child/Grandchild/Nested.md')")
                created = organization.create("Created live", parent=grandchild_context["id"])
                context_notes.resolve(created).create({"title": "New descendant", "body": "Created while parent is open."})
                self.assertEqual(ctl.reconcile_notebooks(), [])
                wait(socket, "!!app.vault.getAbstractFileByPath('Grandchild/Created live/New descendant.md')")
                self.assertTrue((grandchild / "Nested.md").read_text().endswith("Grandchild body.\n"))

                def stop_other():
                    if other_process.poll() is None:
                        other_process.terminate()
                    other_process.wait(timeout=10)

                self.addCleanup(stop_other)
                deadline = time.monotonic() + 30
                other_socket = Path(other_environment["XDG_RUNTIME_DIR"]) / ".obsidian-cli.sock"
                while not other_socket.exists() and time.monotonic() < deadline:
                    self.assertIsNone(other_process.poll(), (base / "other.log").read_text())
                    time.sleep(.1)
                self.assertTrue(other_socket.exists(), "Second profile must be listening before URI delivery")
                # Exercise the real second-instance URI delivery, not just a
                # query parser that silently converts '+' into spaces for us.
                card_name = "A & B + café.md"
                evaluate(socket, "app.vault.create(" + json.dumps(card_name) + ", 'URI acceptance.').then(()=>true)")
                item = {"id": identifier, "runtime_id": "native-fixture"}

                def deliver_uri(arguments, *, env):
                    arguments[0] = os.environ.get("OBSIDIAN_TEST_BINARY", "obsidian")
                    arguments[1:1] = ["--ozone-platform=headless", "--disable-gpu"]
                    result = subprocess.run(arguments, capture_output=True, text=True, timeout=10, env=env)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

                with patch.object(ctl, "state_root", return_value=base), \
                        patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}), \
                        patch.object(ctl, "launch_context", return_value=item), \
                        patch.object(ctl, "notes"), patch.object(ctl, "evaluate"), \
                        patch.object(ctl, "spawn", side_effect=deliver_uri):
                    context_notes.resolve(identifier).open({"path": "Grandchild/Nested.md"})
                wait(socket, "app.workspace.getActiveFile()?.path === 'Grandchild/Nested.md'")
                with patch.object(ctl, "state_root", return_value=base), \
                        patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}), \
                        patch.object(ctl, "launch_context", return_value=item), \
                        patch.object(ctl, "notes"), patch.object(ctl, "evaluate"), \
                        patch.object(ctl, "spawn", side_effect=deliver_uri):
                    context_notes.Vault(vault, identifier).open({"path": card_name})
                wait(socket, "app.workspace.getActiveFile()?.path === " + json.dumps(card_name))
                stop_other()
                evaluate(socket, "app.workspace.getLeaf(false).openFile(app.vault.getAbstractFileByPath('Kanban.base')).then(()=>true)")
                wait(socket, "app.workspace.getActiveFile()?.path === 'Kanban.base'")
                with patch.object(ctl, "state_root", return_value=base), \
                        patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}), \
                        patch.object(ctl, "launch_context", return_value=item), \
                        patch.object(ctl, "notes"), patch.object(ctl, "evaluate"), \
                        patch.object(ctl, "spawn", side_effect=deliver_uri):
                    context_notes.Vault(vault, identifier).open({"path": card_name})
                wait(socket, "app.workspace.getActiveFile()?.path === " + json.dumps(card_name))
                evaluate(socket, "app.workspace.getLeaf(false).openFile(app.vault.getAbstractFileByPath('Kanban.base')).then(()=>true)")
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
                global_profile = base / "obsidian" / notebook_hierarchy.GLOBAL_ID
                global_profile.mkdir()
                global_vault = ctl.root() / ".context/notes"
                global_vault_id = notebook_hierarchy.GLOBAL_ID.replace("-", "")[:16]
                ctl.atomic_json(global_profile / "obsidian.json", {"vaults": {
                    global_vault_id: {"path": str(global_vault), "open": True},
                }})
                notebook.enable_profile(global_profile, global_vault_id)
                if asar := os.environ.get("OBSIDIAN_TEST_ASAR"):
                    shutil.copyfile(asar, global_profile / Path(asar).name)
                with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(runtime)}):
                    global_environment = ctl.obsidian_environment(notebook_hierarchy.GLOBAL_ID)
                global_process, global_connection = launch(global_profile, global_environment, "global.log")
                try:
                    wait(global_connection, "!!window.app?.plugins?.plugins?.['context-notebook']")
                    wait(global_connection, "app.workspace.getActiveFile()?.path === 'Kanban.base'")
                    wait(global_connection, "!!app.vault.getAbstractFileByPath('Parent/Grandchild/Created live/New descendant.md')")
                    wait(global_connection, "document.body.innerText.includes('Parent / Grandchild / Created live')")
                    self.assertEqual(evaluate(global_connection, "app.vault.getMarkdownFiles().filter(f=>f.basename==='Nested').length"), 1)
                finally:
                    global_connection.close()
                    global_process.terminate()
                    global_process.wait(timeout=10)
            finally:
                socket.close()
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
