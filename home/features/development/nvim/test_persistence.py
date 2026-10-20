"""Isolated native tests for the core Neovim persistence adapter.

Run: PERSISTENCE_NATIVE_TESTS=1 python3 home/features/development/nvim/test_persistence.py -v

Requires nvim on PATH; the concurrent RPC test also requires tmux. No lazy plugins
or user configuration are loaded (-u NONE). Fixtures, editor sockets, recovery
files, and the alternate tmux server live in a disposable temporary directory.
The periodic test exercises the real 30-second timer (allow about 35 seconds).
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config"


def lua_string(value):
    """JSON string literals also quote fixture paths safely for Lua/Vimscript."""
    return json.dumps(str(value))


@unittest.skipUnless(
    os.environ.get("PERSISTENCE_NATIVE_TESTS") == "1",
    "set PERSISTENCE_NATIVE_TESTS=1 to run native Neovim tests",
)
class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.nvim = shutil.which("nvim")
        if not self.nvim:
            self.skipTest("nvim not found on PATH")
        parent = Path("/tmp/opencode")
        fixture = tempfile.TemporaryDirectory(
            prefix="nvim-persist-", dir=parent if parent.is_dir() else None
        )
        self.addCleanup(fixture.cleanup)
        self.base = Path(fixture.name).resolve()
        self.home = self.base / "home"
        self.runtime = self.base / "run"
        self.home.mkdir()
        self.runtime.mkdir(mode=0o700)
        self.env = {
            key: value for key, value in os.environ.items()
            if not key.startswith(("CONTEXT_", "NVIM", "TMUX", "PERSISTENCE_TEST_"))
            and key not in {"VIM", "VIMRUNTIME", "VIMINIT", "EXINIT"}
        }
        self.env.update({
            "HOME": str(self.home),
            "XDG_DATA_HOME": str(self.base / "data"),
            "XDG_STATE_HOME": str(self.base / "state"),
            "XDG_CONFIG_HOME": str(self.base / "config"),
            "XDG_CACHE_HOME": str(self.base / "cache"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "TMPDIR": str(self.base),
            "PERSISTENCE_TEST_CONFIG": str(CONFIG),
        })
        self.init = self.base / "init.lua"
        self.init.write_text("""
vim.opt.rtp:prepend(vim.env.PERSISTENCE_TEST_CONFIG)
vim.o.swapfile = false
vim.o.loadplugins = false
if vim.env.PERSISTENCE_TEST_NO_SERVER then
  vim.fn.serverstop(vim.v.servername)
end
require('context_persistence').setup()
""")
        self.env["PERSISTENCE_TEST_INIT"] = str(self.init)
        self.command = [
            self.nvim, "--headless", "-u", "NONE", "-i", "NONE", "-n",
            "--cmd", "lua dofile(vim.env.PERSISTENCE_TEST_INIT)",
        ]
        self.counter = 0

    def run_editor(self, cwd, body="", *, args=(), env=None, stdin=None,
                   expected_error=None):
        """Run assertions after VimEnter, then quit normally to test exit saves."""
        self.counter += 1
        script = self.base / f"check-{self.counter}.lua"
        script.write_text("""
vim.defer_fn(function()
  local ok, err = xpcall(function()
""" + body + """
  end, debug.traceback)
  if not ok then
    io.stderr:write(err .. '\\n')
    vim.cmd('cquit!')
  else
    vim.cmd('qa!')
  end
end, 40)
""")
        result = subprocess.run(
            [*self.command, *args, "-c", "lua dofile(vim.env.PERSISTENCE_TEST_BODY)"],
            cwd=cwd, env={**self.env, **(env or {}), "PERSISTENCE_TEST_BODY": str(script)},
            input=stdin, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        if expected_error:
            self.assertIn(expected_error, result.stderr)
        else:
            self.assertNotIn("Context persistence:", result.stderr, result.stderr)
        return result

    def context(self, name):
        root = self.base / name
        (root / ".context").mkdir(parents=True)
        (root / ".context/context.json").write_text("{}")
        (root / "original.txt").write_text("disk original\n")
        return root

    def test_failed_restore_is_acknowledged_and_cannot_publish_empty_workspace(self):
        root = self.context("missing-original")
        export = self.base / "missing-export"
        self.run_editor(root, "vim.cmd('edit original.txt'); require('context_persistence').checkpoint("
                        + lua_string(export) + ")", env={"CONTEXT_EDITOR_ID": "missing-source"})
        manifest = export / "editor.json"
        before = manifest.read_bytes()
        pointers = {path: path.read_bytes() for path in (root / ".context/state/nvim/directories").glob("*.json")}
        (root / "original.txt").unlink()
        blocked = self.base / "must-not-publish"
        self.run_editor(root,
                        "assert(vim.g.context_persistence_restore_status == 'failed'); "
                        "assert(not pcall(require('context_persistence').checkpoint, " + lua_string(blocked) + "))",
                        env={"CONTEXT_EDITOR_ID": "missing-destination", "CONTEXT_EDITOR_RESTORE": str(manifest)},
                        expected_error="Original file unavailable")
        self.assertFalse(blocked.exists())
        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual({path: path.read_bytes() for path in pointers}, pointers)
        self.assertFalse((root / ".context/state/nvim/editors/missing-destination").exists())

    def storage(self, context=None):
        return (context / ".context/state/nvim" if context else
                self.base / "state/nvim/context-nvim")

    def manifests(self, identity, context=None):
        return sorted(path for path in (self.storage(context) / "current").glob("*/editor.json")
                      if json.loads(path.read_text())["editor_id"] == identity)

    def assert_original(self, root):
        self.assertEqual((root / "original.txt").read_bytes(), b"disk original\n")

    def workspace(self):
        root = self.context("source")
        (root / "sub dir").mkdir()
        (root / "tab dir").mkdir()
        export = self.base / "export with spaces"
        self.run_editor(root, """
vim.cmd('edit original.txt')
vim.api.nvim_buf_set_lines(0, 0, -1, false, {'unsaved named', 'second'})
vim.api.nvim_win_set_cursor(0, {2, 2})
vim.cmd('lcd ' .. vim.fn.fnameescape(vim.fn.getcwd(-1, -1) .. '/sub dir'))
vim.cmd('vsplit')
vim.cmd('enew')
vim.api.nvim_buf_set_lines(0, 0, -1, false, {'unnamed work'})
vim.cmd('split')
vim.cmd('tabnew')
vim.cmd('tcd ' .. vim.fn.fnameescape(vim.fn.getcwd(-1, -1) .. '/tab dir'))
vim.api.nvim_buf_set_lines(0, 0, -1, false, {'tab work'})
local data = vim.json.decode(require('context_persistence').checkpoint(%s))
assert(data.editor_id == 'editor-one')
assert(data.cwd.kind == 'context' and data.cwd.path == '.')
assert(#data.tabs == 2 and data.tabs[1].layout[1] == 'row')
assert(vim.v.servername ~= '')
""" % lua_string(export), args=(".",), env={"CONTEXT_EDITOR_ID": "editor-one"})
        self.assert_original(root)
        self.assertEqual(len(self.manifests("editor-one", root)), 1)
        return root, export

    def test_layout_recovery_directory_autoload_and_moved_context(self):
        root, export = self.workspace()
        first = self.manifests("editor-one", root)[0]
        self.run_editor(root, "assert(#vim.api.nvim_list_tabpages() == 2)",
                        args=(".",), env={"CONTEXT_EDITOR_ID": "editor-two"})
        self.assertTrue(self.manifests("editor-two", root))
        self.assertTrue(first.exists())
        self.assert_original(root)
        moved = self.base / "moved context"
        shutil.copytree(root, moved)
        data = json.loads((export / "editor.json").read_text())
        artifacts = {item["path"]: (export / item["path"]).read_bytes()
                     for item in data["artifacts"]}
        self.run_editor(moved, """
assert(#vim.api.nvim_list_tabpages() == 2)
local first = vim.api.nvim_list_tabpages()[1]
assert(#vim.api.nvim_tabpage_list_wins(first) == 3)
assert(vim.fn.getcwd(-1, -1) == %s)
assert(vim.fn.getcwd(-1, 2) == %s .. '/tab dir')
local found = {}
for _, b in ipairs(vim.api.nvim_list_bufs()) do
  if vim.api.nvim_buf_is_loaded(b) then
    local text = table.concat(vim.api.nvim_buf_get_lines(b, 0, -1, false), '\\n')
    found[text] = true
    if text:match('^unsaved named') then
      assert(vim.b[b].context_original_file == %s .. '/original.txt')
      assert(vim.b[b].context_original_path.kind == 'context')
      assert(vim.api.nvim_buf_get_name(b) ~= vim.b[b].context_original_file)
      assert(vim.bo[b].modified)
      for _, win in ipairs(vim.api.nvim_tabpage_list_wins(first)) do
        if vim.api.nvim_win_get_buf(win) == b then
          local cursor = vim.api.nvim_win_get_cursor(win)
          assert(cursor[1] == 2 and cursor[2] == 2)
          assert(vim.fn.getcwd(win, 1) == %s .. '/sub dir')
        end
      end
      vim.api.nvim_buf_call(b, function() vim.cmd('silent write') end)
    end
  end
end
assert(found['unsaved named\\nsecond'] and found['unnamed work'] and found['tab work'])
""" % ((lua_string(moved),) * 4), args=(".",), env={
            "CONTEXT_EDITOR_ID": "moved-editor", "CONTEXT_DIRECTORY": str(moved),
            "CONTEXT_EDITOR_RESTORE": str(export / "editor.json"),
        })
        self.assert_original(moved)
        for path, contents in artifacts.items():
            self.assertEqual((export / path).read_bytes(), contents)

    def test_explicit_file_and_stdin_override_restore(self):
        root, export = self.workspace()
        env = {"CONTEXT_EDITOR_RESTORE": str(export / "editor.json")}
        self.run_editor(root, """
assert(#vim.api.nvim_list_tabpages() == 1)
assert(vim.api.nvim_buf_get_name(0):match('/original.txt$'))
assert(vim.api.nvim_get_current_line() == 'disk original')
""", args=("original.txt",), env=env)
        self.run_editor(root, """
assert(#vim.api.nvim_list_tabpages() == 1)
assert(vim.api.nvim_get_current_line() == 'stdin content')
""", args=("-",), stdin="stdin content\n", env=env)
        self.assert_original(root)

    def test_sticky_discovered_owner_when_leaving_context(self):
        root = self.context("owner")
        outside = self.base / "outside"
        outside.mkdir()
        for explicit in (False, True):
            with self.subTest(launch_metadata=explicit):
                identity = "owned-explicit" if explicit else "owned-discovered"
                export = self.base / identity
                env = {"CONTEXT_EDITOR_ID": identity}
                if explicit:
                    env["CONTEXT_DIRECTORY"] = str(root)
                self.run_editor(root, """
vim.cmd('cd ' .. vim.fn.fnameescape(%s))
require('context_persistence').checkpoint(%s)
""" % (lua_string(outside), lua_string(export)), env=env)
                self.assertTrue(self.manifests(identity, root))
                self.assertFalse(self.manifests(identity))
                self.assertEqual(json.loads((export / "editor.json").read_text())["cwd"],
                                 {"kind": "external", "path": str(outside)})

    def test_started_outside_uses_local_storage_or_launch_fallback(self):
        outside = self.base / "outside"
        outside.mkdir()
        root = self.context("fallback")
        self.run_editor(outside, env={"CONTEXT_EDITOR_ID": "local"})
        self.assertTrue(self.manifests("local"))
        self.run_editor(outside, env={
            "CONTEXT_EDITOR_ID": "launch-owned", "CONTEXT_DIRECTORY": str(root),
        })
        self.assertTrue(self.manifests("launch-owned", root))
        self.assertFalse(self.manifests("launch-owned"))

    def test_discovered_context_overrides_launch_and_stays_after_leaving(self):
        first = self.context("context-a")
        second = self.context("context-b")
        outside = self.base / "outside"
        outside.mkdir()
        # Each exit proves the storage owner at that point, not just path encoding.
        for leave in (False, True):
            with self.subTest(leave_second=leave):
                identity = "switch-left" if leave else "switch-inside"
                body = "vim.cmd('cd ' .. vim.fn.fnameescape(%s))\n" % lua_string(second)
                if leave:
                    body += "vim.cmd('cd ' .. vim.fn.fnameescape(%s))\n" % lua_string(outside)
                self.run_editor(first, body, env={
                    "CONTEXT_EDITOR_ID": identity, "CONTEXT_DIRECTORY": str(first),
                })
                self.assertTrue(self.manifests(identity, second))
                self.assertFalse(self.manifests(identity, first))
                self.assertFalse(self.manifests(identity))
        # Discovery wins even when the editor launches directly in B with stale A metadata.
        self.run_editor(second, env={
            "CONTEXT_EDITOR_ID": "launch-b", "CONTEXT_DIRECTORY": str(first),
        })
        self.assertTrue(self.manifests("launch-b", second))

    def test_exact_legacy_migration_preserves_source_and_ignores_unrelated(self):
        root = self.context("legacy")
        directory = self.base / "data/nvim/neovim-sessions"
        directory.mkdir(parents=True)
        legacy = directory / str(root).replace(":", "++").replace("/", "__")
        source = "execute 'edit ' . fnameescape(" + lua_string(root / "original.txt") + ")\nlet g:legacy_loaded = 1\n"
        legacy.write_text(source)
        unrelated = directory / "__unrelated"
        unrelated.write_text("let g:unrelated_loaded = 1\n")
        self.run_editor(root, "assert(vim.g.legacy_loaded == 1 and not vim.g.unrelated_loaded)",
                        args=(".",), env={"CONTEXT_EDITOR_ID": "migrated"})
        self.assertEqual(legacy.read_text(), source)
        self.assertEqual(unrelated.read_text(), "let g:unrelated_loaded = 1\n")
        self.assertTrue(self.manifests("migrated", root))
        self.run_editor(self.context("empty"), """
assert(not vim.g.legacy_loaded and not vim.g.unrelated_loaded)
assert(vim.api.nvim_buf_get_name(0) == '')
""")
        self.assert_original(root)

    def test_creates_rpc_socket_when_no_server_exists(self):
        self.run_editor(self.context("socket"), """
assert(vim.v.servername == vim.env.XDG_RUNTIME_DIR .. '/context-nvim-created.sock')
""", env={"PERSISTENCE_TEST_NO_SERVER": "1", "CONTEXT_EDITOR_ID": "created"})

    def test_structured_v1_directory_migration_reclaims_only_known_editor(self):
        root, export = self.workspace()
        data = json.loads((export / "editor.json").read_text())
        data["version"] = 1
        data.pop("publication", None)
        data.pop("integrity", None)
        data["artifacts"] = []
        legacy = self.storage(root) / "editors/legacy/old-generation"
        (legacy / "recovery-old").mkdir(parents=True)
        for entry in data["buffers"]:
            if entry.get("recovery"):
                content = b"".join((export / item["path"]).read_bytes() for item in entry.pop("chunks"))
                entry["recovery"] = f"recovery-old/buffer-{entry['id']}.txt"
                (legacy / entry["recovery"]).write_bytes(content)
                data["artifacts"].append({"path": entry["recovery"], "sha256": hashlib.sha256(content).hexdigest()})
        (legacy / "editor.json").write_text(json.dumps(data))
        key = hashlib.sha256(b"context:.").hexdigest()
        pointer = self.storage(root) / "directories" / (key + ".json")
        pointer.write_text(json.dumps({"version": 1, "editor_id": "legacy", "manifest": "editors/legacy/old-generation/editor.json"}))
        unknown = self.storage(root) / "editors/unknown-incoming/pending"
        unknown.mkdir(parents=True)
        self.run_editor(root, "assert(#vim.api.nvim_list_tabpages()==2)", env={"CONTEXT_EDITOR_ID": "migrated-v1"})
        self.assertEqual(json.loads(pointer.read_text())["version"], 2)
        self.assertFalse(legacy.parent.exists())
        self.assertTrue(unknown.exists(), "unrecognized incoming legacy data must not be swept")
        self.assertTrue(self.manifests("migrated-v1", root))
        self.assert_original(root)

    def test_incremental_standalone_noop_chunks_and_bounded_growth(self):
        root = self.context("incremental")
        self.run_editor(root, r"""
local m = require('context_persistence')
local lines = {}
for i=1,512 do lines[i] = string.format('%04d', i) .. string.rep('x', 1020) end
vim.api.nvim_buf_set_lines(0, 0, -1, false, lines)
m.save()
local function files()
  local result = {}
  local base = vim.fn.getcwd() .. '/.context/state/nvim'
  for _, path in ipairs(vim.fn.glob(base .. '/**/*', false, true)) do
    local stat = vim.uv.fs_stat(path)
    if stat and stat.type == 'file' then result[path] = {size=stat.size, mtime=stat.mtime} end
  end
  return result
end
local before = files()
local uv = vim.uv
local open, rename, unlink, writefile, delete = uv.fs_open, uv.fs_rename, uv.fs_unlink, vim.fn.writefile, vim.fn.delete
local writes = 0
uv.fs_open = function(path, mode, ...)
  if tostring(mode):find('[wa+]') then writes = writes + 1 end
  return open(path, mode, ...)
end
uv.fs_rename = function(...) writes=writes+1; return rename(...) end
uv.fs_unlink = function(...) writes=writes+1; return unlink(...) end
vim.fn.writefile = function(...) writes=writes+1; return writefile(...) end
vim.fn.delete = function(...) writes=writes+1; return delete(...) end
for _=1,25 do m.save() end
assert(writes == 0, 'no-op performed transient writes: ' .. writes)
assert(vim.deep_equal(before, files()), 'no-op changed mtimes or files')
local snapshot = vim.json.decode(m.snapshot())
local old_chunks = snapshot.buffers[1].chunks
vim.api.nvim_buf_set_lines(0, 10, 11, false, {'0011' .. string.rep('y', 1020)})
m.save()
local changed = vim.json.decode(m.snapshot()).buffers[1].chunks
local differences = 0
local old_paths = {}
for _, chunk in ipairs(old_chunks) do old_paths[chunk.path]=true end
for _, chunk in ipairs(changed) do if not old_paths[chunk.path] then differences=differences+1 end end
assert(differences >= 1 and differences <= 3, 'small edit rewrote unrelated large-buffer chunks')
vim.api.nvim_buf_set_lines(0,0,0,false,{'inserted Unicode: 森林 🐈'})
m.save()
local inserted = vim.json.decode(m.snapshot()).buffers[1].chunks
local reused = 0
for _, chunk in ipairs(inserted) do if old_paths[chunk.path] then reused=reused+1 end end
assert(reused >= #old_chunks - 4, 'line insertion rewrote large unchanged suffix')
local initial_count = vim.tbl_count(files())
for edit=1,40 do
  vim.api.nvim_buf_set_lines(0, 10, 11, false, {string.format('%04d',edit) .. string.rep('z',1020)})
  m.save()
end
assert(vim.tbl_count(files()) <= initial_count + 4, 'standalone history grows on each edit')
local manifests = vim.fn.glob(vim.fn.getcwd() .. '/.context/state/nvim/current/*/editor.json', false, true)
local selected = manifests[1]
local committed = table.concat(vim.fn.readfile(selected, 'b'), '\n')
local tracked_rename = uv.fs_rename
uv.fs_rename = function(source, target)
  if target == selected then error('injected root publication crash') end
  return tracked_rename(source, target)
end
vim.api.nvim_buf_set_lines(0,10,11,false,{'after-interruption'})
assert(not pcall(m.save), 'publication failure was hidden')
assert(table.concat(vim.fn.readfile(selected,'b'),'\n') == committed, 'failed publication replaced valid root')
uv.fs_rename = tracked_rename
m.save()
assert(vim.tbl_count(files()) <= initial_count + 4, 'interrupted chunks/scratch were not reclaimed')
assert(#vim.fn.glob(vim.fn.getcwd() .. '/.context/state/nvim/**/*.checkpoint-tmp-*',false,true)==0, 'publication scratch remains')
uv.fs_open, uv.fs_rename, uv.fs_unlink, vim.fn.writefile, vim.fn.delete = open, rename, unlink, writefile, delete
""", env={"CONTEXT_EDITOR_ID": "incremental"})
        self.assertEqual(len(list((self.storage(root) / "current").glob("*/editor.json"))), 1)
        self.assertFalse((self.storage(root) / "editors").exists())

    def test_standalone_divergence_preserves_bytes_after_reordered_sync_deletion(self):
        root = self.context("divergent")
        self.run_editor(root, r"""
local m = require('context_persistence')
vim.api.nvim_buf_set_lines(0,0,-1,false,{'baseline'})
m.save()
local filename = vim.fn.glob(vim.fn.getcwd() .. '/.context/state/nvim/current/*/editor.json',false,true)[1]
local baseline = table.concat(vim.fn.readfile(filename,'b'),'\n')
vim.api.nvim_buf_set_lines(0,0,-1,false,{'local divergent work'})
m.save()
local committed = table.concat(vim.fn.readfile(filename,'b'),'\n')
local local_data = vim.json.decode(committed)
-- Simulate reordered synced older root plus deletion of local referenced bytes.
vim.fn.writefile({baseline},filename,'b')
for _, item in ipairs(local_data.artifacts) do vim.fn.delete(vim.fs.dirname(filename)..'/'..item.path) end
local ok, err = pcall(m.save)
assert(not ok and tostring(err):match('Divergent editor checkpoint preserved'))
local preserved = vim.fs.dirname(filename)..'/conflicts/'..local_data.publication.id..'.json'
assert(vim.deep_equal(vim.json.decode(table.concat(vim.fn.readfile(preserved,'b'),'\n')),local_data))
for _, item in ipairs(local_data.artifacts) do
  local bytes=table.concat(vim.fn.readfile(vim.fs.dirname(filename)..'/'..item.path,'b'),'\n')
  assert(vim.fn.sha256(bytes)==item.sha256, 'divergent chunk lost to synced deletion')
end
-- The explicit failed save was asserted above; avoid a redundant exit notification.
vim.api.nvim_clear_autocmds({group='ContextPersistence',event='VimLeavePre'})
""", env={"CONTEXT_EDITOR_ID": "divergent"})
        self.run_editor(root, "assert(vim.g.context_persistence_restore_status=='failed')",
                        expected_error="Divergent editor checkpoint preserved")

    def test_binary_and_unicode_recovery_bytes_survive_memory_transport(self):
        root = self.context("binary")
        export = self.base / "binary-export"
        body = r"""
local lines = {'a' .. string.char(0) .. 'b', '森林 🐈', 'z' .. string.char(255) .. 'end', string.rep(string.char(128),130000)}
vim.api.nvim_buf_set_lines(0,0,-1,false,lines)
local snapshot = vim.json.decode(require('context_persistence').snapshot())
for _, encoded in pairs(snapshot.contents) do assert(#vim.base64.decode(encoded)<=65536, 'binary chunk exceeds limit') end
require('context_persistence').checkpoint(%s)
""" % lua_string(export)
        self.run_editor(root, body)
        self.run_editor(root, r"""
local lines = vim.api.nvim_buf_get_lines(0,0,-1,false)
assert(vim.deep_equal(lines, {'a' .. string.char(0) .. 'b','森林 🐈','z' .. string.char(255) .. 'end',string.rep(string.char(128),130000)}), 'recovery bytes changed')
""", env={"CONTEXT_EDITOR_RESTORE": str(export / "editor.json")})

    def test_corrupt_selected_recovery_reports_error_without_fallback(self):
        root, export = self.workspace()
        data = json.loads((export / "editor.json").read_text())
        (export / data["artifacts"][0]["path"]).write_text("corrupted")
        self.run_editor(root, "assert(#vim.api.nvim_list_tabpages() == 1)", env={
            "CONTEXT_EDITOR_RESTORE": str(export / "editor.json"),
        }, expected_error="Recovery integrity failure")
        self.assert_original(root)

    def test_concurrent_editors_rpc_alternate_tmux_socket_periodic_and_exit(self):
        binary = shutil.which("tmux")
        if not binary:
            self.skipTest("tmux not found on PATH")
        root = self.context("live")
        socket = self.base / "tmux,isolated.sock"

        def tmux(*args):
            return subprocess.check_output(
                [binary, "-S", str(socket), "-f", "/dev/null", *args],
                env=self.env, text=True, stderr=subprocess.STDOUT, timeout=10,
            ).strip()

        def stop_server():
            subprocess.run([binary, "-S", str(socket), "kill-server"],
                           env=self.env, capture_output=True, timeout=10)

        self.addCleanup(stop_server)
        tmux("new-session", "-d", "-s", "test", "sleep 120")
        tmux("set-option", "-g", "status", "off")
        pane = tmux("display-message", "-p", "#{pane_id}")
        editors = []

        def stop_editor(process):
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

        def rpc(server, expression):
            # RPC clients are noninteractive even when the test runner was
            # launched from a terminal; otherwise Neovim changes output streams.
            return subprocess.check_output(
                [self.nvim, "--server", server, "--remote-expr", expression],
                stdin=subprocess.DEVNULL, env=self.env, text=True, stderr=subprocess.STDOUT, timeout=10,
            )

        for identity in ("live-one", "live-two"):
            process = subprocess.Popen(
                [*self.command, "."], cwd=root,
                env={**self.env, "CONTEXT_EDITOR_ID": identity,
                     "TMUX": f"{socket},123,0", "TMUX_PANE": pane},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.addCleanup(stop_editor, process)
            deadline = time.monotonic() + 5
            while tmux("show-option", "-pqv", "-t", pane, "@persistence-editor") != identity:
                self.assertIsNone(process.poll(), "editor exited before advertising")
                self.assertLess(time.monotonic(), deadline, "editor did not advertise")
                time.sleep(0.03)
            # Wait for both options: publication order need not be deterministic.
            deadline = time.monotonic() + 5
            while True:
                server = tmux("show-option", "-pqv", "-t", pane, "@persistence-editor-socket")
                if server and (not editors or server != editors[0][1]):
                    break
                self.assertLess(time.monotonic(), deadline, "editor socket not updated")
                time.sleep(0.03)
            export = self.base / f"rpc-{identity}"
            expression = ('luaeval("require(\'context_persistence\').checkpoint(_A)", '
                          + lua_string(export) + ')')
            metadata = json.loads(rpc(server, expression))
            self.assertEqual(metadata["editor_id"], identity)
            self.assertEqual(metadata["manifest"], "editor.json")
            self.assertEqual(metadata["cwd"], {"kind": "context", "path": "."})
            self.assertTrue((export / "editor.json").exists())
            rpc(server, 'luaeval("(function() local m=require(\'context_persistence\'); local f=m.checkpoint; '
                        'vim.g.test_saves=0; m.checkpoint=function(...) vim.g.test_saves=vim.g.test_saves+1; '
                        'return f(...) end; return true end)()")')
            editors.append((process, server, identity))

        # No input or tmux status updates: wait for the actual 30-second timer.
        deadline = time.monotonic() + 35
        while not all(int(rpc(server, "get(g:, 'test_saves', 0)")) >= 1 for _, server, _ in editors):
            for process, _, _ in editors:
                self.assertIsNone(process.poll(), "editor exited before periodic save")
            self.assertLess(time.monotonic(), deadline, "periodic save did not run")
            time.sleep(0.1)
        current_paths = set((self.storage(root) / "current").glob("*/editor.json"))
        self.assertEqual(len(current_paths), 1, "one standalone current checkpoint per directory")
        for process, server, identity in editors:
            rpc(server, 'luaeval("vim.schedule(function() vim.cmd(\'qa!\') end) or true")')
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stdout + stderr)
            self.assertNotIn("Context persistence:", stderr)
            self.assertEqual(set(self.manifests(identity, root)), current_paths,
                             "VimLeavePre must update current, never create generations")
        self.assert_original(root)


if __name__ == "__main__":
    unittest.main()
