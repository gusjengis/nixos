"""Native best-effort Neovim session tests, isolated from user config and data.

Run: PERSISTENCE_NATIVE_TESTS=1 python3 test_persistence.py -v
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

CONFIG = Path(__file__).resolve().parent / "config"


@unittest.skipUnless(os.environ.get("PERSISTENCE_NATIVE_TESTS") == "1", "native editor tests opt-in")
class PersistenceTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which("nvim"):
            self.skipTest("nvim unavailable")
        temp = tempfile.TemporaryDirectory(prefix="nvim-sessions-", dir="/tmp/opencode")
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "project with spaces"
        (self.root / ".context").mkdir(parents=True)
        (self.root / ".context/context.json").write_text("{}")
        (self.root / "first.txt").write_text("first disk\nsecond line\n")
        (self.root / "second.txt").write_text("second disk\n")
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("CONTEXT_", "NVIM", "TMUX"))
                    and k not in ("VIM", "VIMRUNTIME", "VIMINIT", "EXINIT")}
        self.env.update({"HOME": str(self.base), "XDG_STATE_HOME": str(self.base / "state"),
                         "XDG_DATA_HOME": str(self.base / "data"), "XDG_CONFIG_HOME": str(self.base / "config"),
                         "XDG_CACHE_HOME": str(self.base / "cache"), "XDG_RUNTIME_DIR": str(self.base)})
        self.init = self.base / "init.lua"
        self.init.write_text("vim.opt.rtp:prepend(" + json.dumps(str(CONFIG)) + "); "
                             "vim.o.swapfile=false; vim.o.loadplugins=false; "
                             "vim.notify=function(...) error('UNEXPECTED NOTIFICATION') end; "
                             "require('context_persistence').setup()")

    def editor(self, code, *, env=None, args=(), stdin=None):
        body = self.base / "body.lua"
        body.write_text("vim.defer_fn(function() local ok,err=xpcall(function()\n" + code +
                        "\nend,debug.traceback); if not ok then io.stderr:write(err..'\\n'); vim.cmd('cquit!') "
                        "else vim.cmd('qa!') end end,40)")
        result = subprocess.run(["nvim", "--headless", "-u", str(self.init), "-i", "NONE", "-n", *args,
                                 "-c", "lua dofile(" + json.dumps(str(body)) + ")"],
                                cwd=self.root, env={**self.env, **(env or {})},
                                input=stdin, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Context persistence:", result.stderr)
        self.assertNotIn("UNEXPECTED NOTIFICATION", result.stderr)
        return result

    def sessions(self):
        return list((self.root / ".context/state/nvim/sessions").glob("*.vim"))

    def test_files_layout_and_cursor_restore_without_unsaved_contents_or_copies(self):
        self.editor("""
vim.cmd('edit first.txt')
vim.api.nvim_win_set_cursor(0,{2,3})
vim.api.nvim_buf_set_lines(0,0,1,false,{'UNSAVED_NAMED_SECRET'})
vim.cmd('vsplit second.txt')
vim.cmd('tabnew second.txt')
vim.cmd('enew')
vim.api.nvim_buf_set_lines(0,0,-1,false,{'UNSAVED_UNNAMED_SECRET'})
assert(require('context_persistence').save())
""")
        self.assertEqual(len(self.sessions()), 1)
        script = self.sessions()[0].read_text()
        self.assertNotIn("UNSAVED_", script)
        self.editor("""
assert(vim.g.context_persistence_restore_status=='ready')
assert(#vim.api.nvim_list_tabpages()==2)
assert(#vim.api.nvim_tabpage_list_wins(vim.api.nvim_list_tabpages()[1])==2)
for _,w in ipairs(vim.api.nvim_tabpage_list_wins(vim.api.nvim_list_tabpages()[1])) do
  if vim.api.nvim_buf_get_name(vim.api.nvim_win_get_buf(w)):match('/first.txt$') then
    local cursor=vim.api.nvim_win_get_cursor(w)
    assert(cursor[1]==2 and cursor[2]==3)
  end
end
local found=false
for _,b in ipairs(vim.api.nvim_list_bufs()) do
  if vim.api.nvim_buf_get_name(b):match('/first.txt$') then
    vim.fn.bufload(b)
    assert(vim.api.nvim_buf_get_lines(b,0,1,false)[1]=='first disk')
    found=true
  end
end
assert(found)
""")
        self.assertEqual((self.root / "first.txt").read_text(), "first disk\nsecond line\n")
        self.assertFalse(list(self.base.rglob("buffer-*.txt")))
        self.assertFalse(list(self.base.rglob("editor.json")))
        self.assertFalse(list(self.base.rglob("objects")))

    def test_corrupt_restore_is_discarded_quietly_and_next_launch_works(self):
        self.editor("vim.cmd('edit first.txt')")
        path = self.sessions()[0]
        path.write_text("edit first.txt\nthrow 'broken session'\n")
        self.editor("""
assert(vim.g.context_persistence_restore_status=='discarded')
assert(vim.api.nvim_buf_get_name(0)=='')
assert(require('context_persistence').save())
""")
        self.assertNotIn("broken session", path.read_text())
        self.editor("assert(vim.g.context_persistence_restore_status=='ready')")

    def test_failed_saves_are_quiet_remove_stale_session_and_do_not_poison_editor(self):
        self.editor("vim.cmd('edit first.txt')")
        self.editor("""
local p=require('context_persistence')
local command=vim.cmd
local options=vim.o.sessionoptions
vim.cmd=function() error('intentional write failure') end
for i=1,20 do assert(not p.save()) end
assert(vim.o.sessionoptions==options)
vim.cmd=command
assert(#vim.fn.glob('.context/state/nvim/sessions/*.vim',false,true)==0)
assert(p.save())
""")
        log = self.base / "state/nvim/context-nvim/sessions.log"
        self.assertEqual(log.read_text().count("intentional write failure"), 1)
        self.assertEqual(len(self.sessions()), 1)

    def test_explicit_file_and_stdin_skip_automatic_restore(self):
        self.editor("vim.cmd('edit first.txt'); vim.cmd('tabnew second.txt')")
        self.editor("assert(#vim.api.nvim_list_tabpages()==1); assert(vim.api.nvim_buf_get_name(0):match('/second.txt$'))",
                    args=("second.txt",))
        self.editor("assert(vim.api.nvim_get_current_line()=='stdin text')", args=("-",), stdin="stdin text\n")

    def test_deleted_file_does_not_block_startup_or_subsequent_saves(self):
        self.editor("vim.cmd('edit first.txt'); vim.cmd('vsplit second.txt')")
        (self.root / "first.txt").unlink()
        self.editor("assert(vim.g.context_persistence_restore_status=='ready'); assert(require('context_persistence').save())")

    def test_old_buffer_recovery_is_not_loaded(self):
        manifest = self.base / "editor.json"
        manifest.write_text(json.dumps({"version": 2, "buffers": [{"original": {"kind": "external", "path": "bad"}}]}))
        self.editor("assert(vim.g.context_persistence_restore_status=='discarded'); assert(require('context_persistence').save())",
                    env={"CONTEXT_EDITOR_RESTORE": str(manifest)})
        self.assertFalse(manifest.exists())

    def test_snapshot_contains_only_builtin_session_not_buffer_text(self):
        snapshot = self.base / "snapshot.json"
        self.editor("""
vim.cmd('edit first.txt')
vim.api.nvim_buf_set_lines(0,0,-1,false,{'UNSAVED_SECRET'})
vim.fn.writefile({require('context_persistence').snapshot()},%s)
""" % json.dumps(str(snapshot)))
        import base64
        data = json.loads(snapshot.read_text())
        self.assertEqual(data["version"], 3)
        self.assertEqual(list(data["contents"]), ["session.vim"])
        self.assertNotIn(b"UNSAVED_SECRET", base64.b64decode(data["contents"]["session.vim"]))


if __name__ == "__main__":
    unittest.main()
