import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import contextctl
import repositories


spec = importlib.util.spec_from_file_location("migrate_repos", Path(__file__).with_name("migrate-repos.py"))
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "home/Documents/Code"
        self.source.mkdir(parents=True)
        self.root = self.base / "sessions"
        environment = patch.dict(os.environ, {
            "HOME": str(self.base / "home"), "CONTEXT_ROOT": str(self.root),
            "XDG_STATE_HOME": str(self.base / "state"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        sync = patch.object(repositories, "sync", return_value={"live": True})
        self.sync = sync.start()
        self.addCleanup(sync.stop)
        self.real_git = os.environ.get("CONTEXT_REAL_GIT") or "/run/current-system/sw/bin/git"
        if not Path(self.real_git).is_file():
            self.real_git = shutil.which("git")

    def git(self, directory, *args):
        return subprocess.run([self.real_git, "-C", str(directory), *args], check=True,
                              capture_output=True, text=True).stdout

    def repo(self, name):
        directory = self.source / name
        directory.mkdir(parents=True)
        self.git(directory, "init", "-q")
        (directory / "tracked").write_text("original\n")
        self.git(directory, "add", "tracked")
        (directory / "tracked").write_text("dirty\n")
        (directory / "untracked").write_bytes(b"\x00precious\xff")
        return directory

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = migration.main(["--source", str(self.source), "--json", *args])
        return result, json.loads(output.getvalue())

    def snapshot(self):
        return {str(path.relative_to(self.base)): (path.lstat().st_mode,
                os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None)
                for path in self.base.rglob("*")}

    def test_dry_run_changes_nothing(self):
        self.repo("alpha")
        before = self.snapshot()
        result, report = self.run_cli()
        self.assertEqual(result, 0)
        self.assertFalse(report["apply"])
        self.assertEqual(report["entries"][0]["status"], "ready")
        self.assertEqual(before, self.snapshot())

    def test_rename_preserves_dirty_work_and_context_outside_git(self):
        source = self.repo("alpha")
        inode = source.stat().st_ino
        status = self.git(source, "status", "--porcelain")
        result, report = self.run_cli("--apply")
        self.assertEqual(result, 0)
        target = self.root / "alpha/alpha"
        self.assertTrue(source.is_symlink())
        self.assertEqual(source.resolve(), target)
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(self.git(target, "status", "--porcelain"), status)
        self.assertEqual((target / "untracked").read_bytes(), b"\x00precious\xff")
        self.assertFalse((target / ".context").exists())
        metadata = contextctl.read_json(self.root / "alpha/.context/context.json")
        self.assertEqual(metadata["working_directory"], "alpha")
        self.assertEqual(metadata["repositories"], [{"path": "alpha"}])
        self.sync.assert_called_once_with(self.root, require_live=True)
        record = migration.read_journal()["records"][0]
        self.assertEqual(record, {"source": str(source), "target": str(target),
                                  "uuid": metadata["id"], "status": "moved"})
        self.assertEqual(report["entries"][0]["uuid"], metadata["id"])

    def test_nested_aur_and_nonrepositories(self):
        self.repo("AUR/hyprlog")
        loose = self.source / "loose"
        loose.mkdir()
        (loose / "notes").write_text("keep")
        self.repo(".hidden/secret")
        self.repo("outer")
        self.repo("outer/nested")
        self.assertEqual(self.run_cli("--apply")[0], 0)
        self.assertTrue((self.root / "AUR/hyprlog/hyprlog/.git").is_dir())
        self.assertFalse((self.root / "AUR/.context").exists())
        self.assertEqual((loose / "notes").read_text(), "keep")
        self.assertFalse((self.root / ".hidden").exists())
        self.assertFalse((self.root / "outer/nested").exists())
        self.assertTrue((self.root / "outer/outer/nested/.git").is_dir())

    def test_git_files_skipped_without_descending(self):
        for name in ("worktree", "submodule"):
            directory = self.source / name
            directory.mkdir()
            (directory / ".git").write_text("gitdir: /some/absolute/path\n")
            self.repo(f"{name}/nested")
        before = self.snapshot()
        result, report = self.run_cli()
        self.assertEqual(result, 0)
        self.assertEqual([item["status"] for item in report["entries"]], ["skipped", "skipped"])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.run_cli("--apply")[0], 0)
        self.assertFalse(self.root.exists())

    def test_conflicts_reported_before_any_move_and_skipped_on_apply(self):
        self.repo("alpha")
        blocked = self.repo("blocked")
        target = self.root / "blocked/blocked"
        target.mkdir(parents=True)
        (target / "precious").write_text("pre-provisioned")
        original_plan = migration.plan

        def inspect(source):
            self.assertFalse((self.source / "alpha").is_symlink())
            entries = original_plan(source)
            self.assertEqual(entries[1]["status"], "conflict")
            return entries

        with patch.object(migration, "plan", side_effect=inspect):
            result, report = self.run_cli("--apply")
        self.assertEqual(result, 1)
        self.assertEqual([item["status"] for item in report["entries"]], ["moved", "conflict"])
        self.assertFalse(blocked.is_symlink())
        self.assertEqual((target / "precious").read_text(), "pre-provisioned")

    def test_idempotent_and_preserves_journal(self):
        self.repo("alpha")
        self.assertEqual(self.run_cli("--apply")[0], 0)
        journal = migration.read_journal()
        journal["records"].append({"source": "old", "target": "other", "uuid": "retained"})
        contextctl.atomic_json(migration.journal_path(), journal)
        before = self.snapshot()
        result, report = self.run_cli("--apply")
        self.assertEqual(result, 0)
        self.assertEqual(report["entries"][0]["status"], "already-migrated")
        self.assertEqual(before, self.snapshot())

    def test_existing_empty_context_reused(self):
        self.repo("alpha")
        data = contextctl.create("alpha", "alpha")
        self.assertEqual(self.run_cli("--apply")[0], 0)
        self.assertEqual(migration.read_journal()["records"][0]["uuid"], data["id"])

    def test_later_moves_append_without_replacing_records(self):
        self.repo("alpha")
        self.assertEqual(self.run_cli("--apply")[0], 0)
        original = migration.read_journal()["records"][0]
        self.repo("beta")
        self.assertEqual(self.run_cli("--apply")[0], 0)
        records = migration.read_journal()["records"]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], original)
        self.assertEqual(records[1]["source"], str(self.source / "beta"))

    def test_different_existing_context_is_conflict(self):
        source = self.repo("alpha")
        contextctl.create("alpha", ".")
        result, report = self.run_cli("--apply")
        self.assertEqual(result, 1)
        self.assertEqual(report["entries"][0]["status"], "conflict")
        self.assertFalse(source.is_symlink())

    def test_target_symlink_and_file_parent_are_conflicts(self):
        self.repo("alpha")
        self.repo("beta")
        (self.root / "alpha").mkdir(parents=True)
        (self.root / "alpha/alpha").symlink_to(self.base / "missing")
        (self.root / "beta").mkdir()
        (self.root / "beta/beta").write_text("keep")
        result, report = self.run_cli("--apply")
        self.assertEqual(result, 1)
        self.assertEqual([item["status"] for item in report["entries"]], ["conflict", "conflict"])
        self.assertEqual((self.root / "beta/beta").read_text(), "keep")

    def test_source_symlinks_never_traversed(self):
        self.repo("alpha")
        (self.source / "alias").symlink_to(self.source / "alpha", target_is_directory=True)
        result, report = self.run_cli("--apply")
        self.assertEqual(result, 0)
        self.assertEqual(report["entries"][0]["status"], "skipped")
        self.assertFalse((self.root / "alias").exists())

    def test_cyclic_source_symlink_skipped(self):
        (self.source / "loop").symlink_to("loop")
        self.assertEqual(self.run_cli()[1]["entries"][0]["status"], "skipped")

    def test_unsafe_roots_rejected_without_changes(self):
        self.repo("alpha")
        for root in (self.source / "nested", self.base, self.source / "alpha/.git/contexts"):
            with self.subTest(root=root):
                before = self.snapshot()
                result, report = self.run_cli("--root", str(root), "--apply")
                self.assertEqual(result, 1)
                self.assertIn("error", report)
                self.assertEqual(before, self.snapshot())

    def test_cross_filesystem_conflict(self):
        self.repo("alpha")
        original = Path.stat

        def changed_device(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == self.source / "alpha":
                fields = list(value)
                fields[2] += 1
                return os.stat_result(fields)
            return value

        before = self.snapshot()
        with patch.object(Path, "stat", changed_device):
            result, report = self.run_cli()
        self.assertEqual(result, 1)
        self.assertIn("same-filesystem", report["entries"][0]["reason"])
        self.assertEqual(before, self.snapshot())

    def test_symlink_failure_rolls_repo_back_and_journals_failure(self):
        source = self.repo("alpha")
        with patch.object(Path, "symlink_to", side_effect=OSError("cannot link")):
            self.assertEqual(self.run_cli("--apply")[0], 1)
        self.assertFalse(source.is_symlink())
        self.assertTrue((source / ".git").is_dir())
        self.assertEqual(migration.read_journal()["records"][0]["status"], "failed")

    def test_corrupt_journal_blocks_all_moves(self):
        source = self.repo("alpha")
        contextctl.atomic_json(migration.journal_path(), {"version": 1, "records": ["bad"]})
        before = self.snapshot()
        self.assertEqual(self.run_cli("--apply")[0], 1)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(source.is_symlink())

    def test_live_exclusions_required_before_rename(self):
        source = self.repo("alpha")

        def unavailable(root, *, require_live):
            self.assertTrue(require_live)
            self.assertTrue(source.is_dir())
            self.assertFalse(source.is_symlink())
            metadata = contextctl.read_json(root / "alpha/.context/context.json")
            self.assertEqual(metadata["repositories"], [{"path": "alpha"}])
            raise repositories.RepositoryError("offline")

        self.sync.side_effect = unavailable
        self.assertEqual(self.run_cli("--apply")[0], 1)
        self.assertTrue((source / ".git").is_dir())
        self.assertFalse((self.root / "alpha/alpha").exists())


if __name__ == "__main__":
    unittest.main()
