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


spec = importlib.util.spec_from_file_location("flatten_repos", Path(__file__).with_name("flatten-repos.py"))
flatten = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flatten)


class FlattenTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "sessions"
        self.home = self.base / "home"
        environment = patch.dict(os.environ, {
            "HOME": str(self.home), "CONTEXT_ROOT": str(self.root),
            "XDG_STATE_HOME": str(self.base / "state"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.real_git = os.environ.get("CONTEXT_REAL_GIT") or "/run/current-system/sw/bin/git"
        if not Path(self.real_git).is_file():
            self.real_git = shutil.which("git")
        sync = patch.object(repositories, "sync", side_effect=self.live_sync)
        self.sync = sync.start()
        self.addCleanup(sync.stop)

    def live_sync(self, root, *, require_live):
        self.assertTrue(require_live)
        return repositories._sync(root, offline=True) | {"live": True}

    def git(self, directory, *args):
        return subprocess.run([self.real_git, "-C", str(directory), *args], check=True,
                              capture_output=True, text=True).stdout

    def repo(self, name="Alpha", leaf="Repo"):
        # Create all contexts before checkouts where tests need more than one.
        context = self.root / name
        if not (context / ".context").exists():
            contextctl.create(name, f"work/{leaf}")
        source = context / "work" / leaf
        source.mkdir(parents=True)
        self.git(source, "init", "-q")
        (source / "tracked").write_text("original\n")
        self.git(source, "add", "tracked")
        (source / "tracked").write_text("dirty\n")
        (source / "untracked").write_bytes(b"\x00precious\xff")
        metadata = context / ".context/context.json"
        data = contextctl.read_json(metadata)
        data["custom"] = {"keep": True}
        contextctl.atomic_json(metadata, data)
        return source, context / leaf, metadata

    def run_cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = flatten.main(["--json", *args])
        return result, json.loads(output.getvalue())

    def snapshot(self):
        return {str(path.relative_to(self.base)): (path.lstat().st_mode,
                os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None)
                for path in self.base.rglob("*")}

    def original_link(self, source, metadata, name="Repo", identifier=None, target=None):
        link = self.home / "Documents/Code" / name
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(target or source, target_is_directory=True)
        path = contextctl.state_root() / "repo-migration.json"
        journal = contextctl.read_json(path, {"version": 1, "records": []})
        journal["records"].append({"source": str(link), "target": str(source),
                                   "uuid": identifier or contextctl.read_json(metadata)["id"], "status": "moved"})
        contextctl.atomic_json(path, journal)
        return link

    def test_dry_run_read_only_and_known_uuid(self):
        source, target, metadata = self.repo("AUR/Alpha")
        before = self.snapshot()
        with patch.object(contextctl, "scan", side_effect=AssertionError("unsafe scan")):
            result, report = self.run_cli()
        self.assertEqual(result, 0)
        entry = report["entries"][0]
        self.assertEqual((entry["source"], entry["target"], entry["uuid"]),
                         (str(source), str(target), contextctl.read_json(metadata)["id"]))
        self.assertEqual(before, self.snapshot())
        self.sync.assert_not_called()

    def test_prepare_both_paths_no_move_preserves_fields_and_url(self):
        source, target, metadata = self.repo()
        data = contextctl.read_json(metadata)
        data["repositories"] = [{"path": "work/Repo", "url": "ssh://example/repo", "custom": "preserve"}]
        contextctl.atomic_json(metadata, data)
        self.assertEqual(self.run_cli("--prepare")[0], 0)
        prepared = contextctl.read_json(metadata)
        self.assertEqual(prepared, data | {"repositories": data["repositories"] + [dict(data["repositories"][0], path="Repo")]})
        self.assertTrue(source.is_dir())
        self.assertFalse(target.exists())
        self.assertEqual(flatten.read_journal()["records"][0]["status"], "prepared")
        before = self.snapshot()
        self.assertEqual(self.run_cli("--prepare")[0], 0)
        self.assertEqual(before, self.snapshot())
        self.sync.assert_not_called()

    def test_flatten_preserves_repository_record_fields(self):
        _, _, metadata = self.repo()
        data = contextctl.read_json(metadata)
        data["repositories"] = [{"path": "work/Repo", "url": "https://example.org/repo.git", "custom": {"keep": True}}]
        contextctl.atomic_json(metadata, data)
        self.assertEqual(self.run_cli("--prepare")[0], 0)
        self.assertEqual(self.run_cli("--apply")[0], 0)
        self.assertEqual(contextctl.read_json(metadata)["repositories"], [dict(data["repositories"][0], path="Repo")])

    def test_conflicting_flat_record_blocks_prepare_without_changes(self):
        _, _, metadata = self.repo()
        data = contextctl.read_json(metadata)
        data["repositories"] = [{"path": "work/Repo", "url": "https://example.org/old"},
                                {"path": "Repo", "url": "https://example.org/other"}]
        contextctl.atomic_json(metadata, data)
        before = metadata.read_bytes()
        self.assertEqual(self.run_cli("--prepare")[0], 1)
        self.assertEqual(metadata.read_bytes(), before)

    def test_apply_preserves_inode_dirt_fields_links_and_historical_excludes(self):
        source, target, metadata = self.repo()
        inode, status = source.stat().st_ino, self.git(source, "status", "--porcelain")
        link = self.original_link(source, metadata)
        unrelated = self.original_link(source, metadata, "Other", identifier="other-user-context")
        changed = self.original_link(source, metadata, "Changed", target=self.base / "elsewhere")
        original_journal = (contextctl.state_root() / "repo-migration.json").read_bytes()
        self.assertEqual(self.run_cli("--prepare")[0], 0)
        self.assertEqual(self.run_cli("--apply")[0], 0)
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(self.git(target, "status", "--porcelain"), status)
        self.assertEqual((target / "untracked").read_bytes(), b"\x00precious\xff")
        self.assertFalse(os.path.lexists(source.parent))
        self.assertEqual(os.readlink(link), str(target))
        self.assertEqual(os.readlink(unrelated), str(source))
        self.assertEqual(os.readlink(changed), str(self.base / "elsewhere"))
        self.assertEqual((contextctl.state_root() / "repo-migration.json").read_bytes(), original_journal)
        data = contextctl.read_json(metadata)
        self.assertEqual(data["working_directory"], "Repo")
        self.assertEqual(data["repositories"], [{"path": "Repo"}])
        self.assertEqual(data["custom"], {"keep": True})
        self.assertFalse((target / ".context").exists())
        paths = repositories._sync(self.root, offline=True)["paths"]
        self.assertEqual(paths, ["Alpha/Repo", "Alpha/work/Repo"])
        self.assertEqual(flatten.read_journal()["records"][0]["status"], "moved")
        before = self.snapshot()
        self.assertEqual(self.run_cli("--prepare")[0], 0)
        self.assertEqual(self.run_cli("--apply")[0], 0)
        self.assertEqual(before, self.snapshot())

    def test_work_siblings_preserved(self):
        source, target, _ = self.repo()
        (source.parent / "notes.txt").write_text("keep")
        self.run_cli("--prepare")
        self.assertEqual(self.run_cli("--apply")[0], 0)
        self.assertEqual((source.parent / "notes.txt").read_text(), "keep")
        self.assertFalse(os.path.lexists(source))
        self.assertTrue(target.is_dir())

    def test_apply_requires_prepare_and_live_confirmation(self):
        source, target, _ = self.repo()
        self.assertEqual(self.run_cli("--apply")[0], 1)
        self.sync.assert_not_called()
        self.run_cli("--prepare")
        for failure in (repositories.RepositoryError("offline"), {"live": False}):
            with self.subTest(failure=failure):
                if isinstance(failure, Exception):
                    self.sync.side_effect = failure
                else:
                    self.sync.side_effect = None
                    self.sync.return_value = failure
                self.assertEqual(self.run_cli("--apply")[0], 1)
                self.assertTrue(source.is_dir())
                self.assertFalse(target.exists())

    def test_live_check_precedes_every_move(self):
        first, _, _ = self.repo()
        second, _, _ = self.repo("Beta")
        self.run_cli("--prepare")

        def confirm(root, *, require_live):
            self.assertTrue(first.is_dir())
            self.assertTrue(second.is_dir())
            self.assertEqual(len(repositories.registered(root)), 4)
            return self.live_sync(root, require_live=require_live)

        self.sync.side_effect = confirm
        self.assertEqual(self.run_cli("--apply")[0], 0)
        self.sync.assert_called_once_with(self.root, require_live=True)

    def test_collision_blocks_entire_batch_before_prepare_or_moves(self):
        source, _, _ = self.repo()
        _, target, _ = self.repo("Beta")
        target.symlink_to(self.base / "missing")
        for mode in ("--prepare", "--apply"):
            before = self.snapshot()
            self.assertEqual(self.run_cli(mode)[0], 1)
            self.assertEqual(before, self.snapshot())
        self.assertTrue(source.is_dir())
        self.sync.assert_not_called()

    def test_walk_prunes_work_hidden_and_registered_checkouts(self):
        source, _, metadata = self.repo()
        for parent in (source / "deep", source.parent / "unregistered", self.root / ".hidden", self.root / "Alpha/Registered/deep"):
            (parent / ".context").mkdir(parents=True)
            (parent / ".context/context.json").write_text("invalid")
        data = contextctl.read_json(metadata)
        data["repositories"] = [{"path": "Registered"}]
        contextctl.atomic_json(metadata, data)
        with patch.object(contextctl, "scan", side_effect=AssertionError("unsafe scan")):
            self.assertEqual(self.run_cli("--prepare")[0], 0)

    def test_invalid_later_context_blocks_all_metadata_changes(self):
        self.repo()
        broken = self.root / "Zulu/.context"
        broken.mkdir(parents=True)
        (broken / "context.json").write_text("{}")
        before = self.snapshot()
        self.assertEqual(self.run_cli("--prepare")[0], 1)
        # Lock file is permitted for mutation attempts, but metadata must be untouched.
        after = self.snapshot()
        self.assertEqual({key: value for key, value in after.items() if key in before}, before)
        self.assertFalse(flatten.journal_path().exists())

    def test_git_file_skipped_and_nonexact_legacy_cwd_not_planned(self):
        source, _, metadata = self.repo()
        shutil.rmtree(source / ".git")
        (source / ".git").write_text("gitdir: /outside\n")
        self.assertEqual(self.run_cli("--prepare")[1]["entries"][0]["status"], "skipped")
        self.sync.assert_not_called()
        data = contextctl.read_json(metadata)
        data["working_directory"] = "work/Repo/deeper"
        contextctl.atomic_json(metadata, data)
        self.assertEqual(self.run_cli()[1]["entries"], [])

    def test_cross_filesystem_conflict(self):
        source, _, _ = self.repo()
        original = Path.stat

        def changed(path, *args, **kwargs):
            value = original(path, *args, **kwargs)
            if path == source:
                fields = list(value)
                fields[2] += 1
                return os.stat_result(fields)
            return value

        with patch.object(Path, "stat", changed):
            result, report = self.run_cli("--prepare")
        self.assertEqual(result, 1)
        self.assertIn("same-filesystem", report["entries"][0]["reason"])

    def test_metadata_failure_rolls_back_repo_link_and_prepared_metadata(self):
        source, target, metadata = self.repo()
        link = self.original_link(source, metadata)
        self.run_cli("--prepare")
        before = metadata.read_bytes()
        original = contextctl.atomic_json

        def fail(path, data):
            if path == metadata and data["working_directory"] == "Repo":
                raise OSError("metadata write failed")
            return original(path, data)

        with patch.object(contextctl, "atomic_json", side_effect=fail):
            result, report = self.run_cli("--apply")
        self.assertEqual(result, 1)
        self.assertIn("Keep sessions paused", report["error"])
        self.assertTrue(source.is_dir())
        self.assertFalse(target.exists())
        self.assertEqual(os.readlink(link), str(source))
        self.assertEqual(metadata.read_bytes(), before)
        self.assertEqual(flatten.read_journal()["records"][0]["status"], "failed")
        self.assertEqual(self.run_cli("--prepare")[0], 0)
        self.assertEqual(self.run_cli("--apply")[0], 0)

    def test_interrupted_journal_requires_explicit_recovery(self):
        source, target, _ = self.repo()
        self.run_cli("--prepare")
        journal = flatten.read_journal()
        journal["records"][0]["status"] = "moving"
        contextctl.atomic_json(flatten.journal_path(), journal)
        source.rename(target)
        before = self.snapshot()
        result, report = self.run_cli("--apply")
        self.assertEqual(result, 1)
        self.assertIn("Interrupted flatten transaction", report["error"])
        self.assertEqual(before, self.snapshot())

    def test_symlink_failure_rolls_back_without_work_symlink(self):
        source, target, metadata = self.repo()
        self.original_link(source, metadata)
        self.run_cli("--prepare")
        with patch.object(Path, "symlink_to", side_effect=OSError("cannot link")):
            self.assertEqual(self.run_cli("--apply")[0], 1)
        self.assertTrue(source.is_dir())
        self.assertFalse(source.is_symlink())
        self.assertFalse(target.exists())

    def test_final_journal_write_failure_rolls_back_persisted_metadata(self):
        source, target, metadata = self.repo()
        link = self.original_link(source, metadata)
        self.run_cli("--prepare")
        before = metadata.read_bytes()
        original = contextctl.atomic_json

        def fail(path, data):
            if path == flatten.journal_path() and data["records"][0]["status"] == "moved":
                raise OSError("journal persistence failed")
            return original(path, data)

        with patch.object(contextctl, "atomic_json", side_effect=fail):
            self.assertEqual(self.run_cli("--apply")[0], 1)
        self.assertTrue(source.is_dir())
        self.assertFalse(target.exists())
        self.assertEqual(metadata.read_bytes(), before)
        self.assertEqual(os.readlink(link), str(source))
        self.assertEqual(flatten.read_journal()["records"][0]["status"], "failed")

    def test_failed_rollback_records_recovery_required_and_blocks_rerun(self):
        source, target, metadata = self.repo()
        self.run_cli("--prepare")
        atomic, rename = contextctl.atomic_json, Path.rename

        def fail_metadata(path, data):
            if path == metadata and data["working_directory"] == "Repo":
                raise OSError("metadata persistence failed")
            return atomic(path, data)

        def fail_rollback(path, destination):
            if path == target:
                raise OSError("rollback rename failed")
            return rename(path, destination)

        with patch.object(contextctl, "atomic_json", side_effect=fail_metadata), \
                patch.object(Path, "rename", fail_rollback):
            self.assertEqual(self.run_cli("--apply")[0], 1)
        self.assertFalse(source.exists())
        self.assertTrue(target.is_dir())
        journal = contextctl.read_json(flatten.journal_path())
        self.assertEqual(journal["records"][0]["status"], "recovery-required")
        self.assertIn("never overwrite", journal["records"][0]["recovery"])
        self.assertEqual(self.run_cli("--prepare")[0], 1)

    def test_prepare_json_contains_all_36_original_ids_and_paths(self):
        expected = []
        for number in range(36):
            source, target, metadata = self.repo(f"Repo{number:02}")
            expected.append((str(source), str(target), contextctl.read_json(metadata)["id"]))
        with patch.object(contextctl, "scan", side_effect=AssertionError("unsafe scan")):
            result, report = self.run_cli("--prepare")
        self.assertEqual(result, 0)
        self.assertEqual([(item["source"], item["target"], item["uuid"]) for item in report["entries"]], expected)
        self.assertEqual({item["status"] for item in report["entries"]}, {"prepared"})
        self.assertEqual(len(flatten.read_journal()["records"]), 36)
        self.assertTrue(all(Path(source).is_dir() and not Path(target).exists()
                            for source, target, _ in expected))


if __name__ == "__main__":
    unittest.main()
