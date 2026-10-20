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

import repositories


spec = importlib.util.spec_from_file_location("context_git", Path(__file__).with_name("context-git.py"))
wrapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wrapper)


class ContextGitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "sessions"
        self.context = self.root / "project"
        (self.context / ".context").mkdir(parents=True)
        self.metadata = self.context / ".context/context.json"
        self.metadata.write_text(json.dumps({"version": 1, "working_directory": ".", "notes": "keep"}))
        environment = patch.dict(os.environ, {
            "HOME": str(self.base), "CONTEXT_ROOT": str(self.root),
            "CONTEXT_REAL_GIT": "/nix/store/fake-git/bin/git",
            "XDG_STATE_HOME": str(self.base / "state"),
            "XDG_CONFIG_HOME": str(self.base / "config"),
        })
        environment.start()
        self.addCleanup(environment.stop)
        for name in list(os.environ):
            if name.startswith("GIT_"):
                del os.environ[name]
        os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
        os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
        cwd = Path.cwd()
        os.chdir(self.base)
        self.addCleanup(os.chdir, cwd)
        self.events = []
        sync = patch.object(repositories, "sync", side_effect=self.sync)
        self.sync_mock = sync.start()
        self.addCleanup(sync.stop)
        run = patch.object(wrapper.subprocess, "run", side_effect=self.run_git)
        self.run_mock = run.start()
        self.addCleanup(run.stop)

    def sync(self, root, *, require_live):
        self.assertEqual(root, self.root)
        self.assertTrue(require_live)
        self.assertTrue(repositories.registered(root))
        self.events.append("sync")
        return {"live": True}

    def run_git(self, args):
        self.events.append("git")
        return subprocess.CompletedProcess(args, 0)

    def invoke(self, *args):
        with contextlib.redirect_stderr(io.StringIO()) as errors:
            code = wrapper.main(list(args))
        return code, errors.getvalue()

    def records(self):
        return json.loads(self.metadata.read_text()).get("repositories", [])

    def test_clone_order_original_arguments_and_metadata(self):
        args = ["-C", str(self.root), "-Cproject", "-c", "color.ui=false", "-ccore.autocrlf=false",
                "--config-env=credential.helper=TEST_HELPER", "clone", "--depth", "1",
                "--branch=main", "--recurse-submodules=lib", "https://example.org/repo.git", "work/repo"]
        with patch.dict(os.environ, {"TEST_HELPER": ""}):
            self.assertEqual(self.invoke(*args)[0], 0)
        self.assertEqual(self.events, ["sync", "git"])
        self.run_mock.assert_called_once_with([os.environ["CONTEXT_REAL_GIT"], *args])
        self.assertEqual(self.records(), [{"path": "work/repo", "url": "https://example.org/repo.git"}])
        self.assertEqual(json.loads(self.metadata.read_text())["working_directory"], ".")
        self.assertFalse((self.context / "work").exists())

    def test_outside_passthrough_and_other_subcommands(self):
        for args in (["clone", "--future", "remote", "outside"], ["init", "--separate-git-dir", "meta", "outside"],
                     ["-C", str(self.context), "status"], ["-C", str(self.context), "worktree", "add", "new"],
                     ["--help"], ["-C", str(self.context), "clone", "--help"],
                     ["-C", str(self.context), "clone", "remote", str(self.base / "outside")]):
            with self.subTest(args=args):
                self.assertEqual(self.invoke(*args)[0], 0)
                self.assertEqual(self.run_mock.call_args.args[0][1:], args)
        self.assertFalse(self.sync_mock.called)
        self.assertEqual(self.records(), [])

    def test_absolute_destination_from_outside_and_symlink_parents(self):
        (self.base / "alias").symlink_to(self.context, target_is_directory=True)
        self.assertEqual(self.invoke("clone", "git@example.org:team/repo.git",
                                     str(self.base / "alias/work/repo"))[0], 0)
        self.assertEqual(self.records(), [{"path": "work/repo"}])

    def test_default_clone_names(self):
        for remote, bare, expected in [
            ("https://example.org/team/repo.git", False, "repo"),
            ("git@example.org:team/repo.git", False, "repo"),
            ("ssh://git@example.org/team/repo.git/", False, "repo"),
            ("/tmp/source/.git", False, "source"),
            ("/tmp/source.git", True, "source.git"),
        ]:
            with self.subTest(remote=remote):
                self.assertEqual(wrapper._clone_name(remote, bare), expected)
        self.assertEqual(self.invoke("-C", str(self.context), "clone", "--mirror", "https://example.org/repo.git")[0], 0)
        self.assertEqual(self.records()[0]["path"], "repo.git")

    def test_common_clone_option_values(self):
        args = ["-C", str(self.context), "clone"]
        for option in sorted(wrapper.CLONE_VALUES - {"--separate-git-dir"}):
            args.extend([option, "x=y" if option == "--config" else "value"])
        args.extend(["-bmain", "-oorigin", "-cfoo.bar=baz", "-uupload", "-j4", "-qv",
                     "--recursive", "--no-checkout", "remote", "destination"])
        self.assertEqual(self.invoke(*args)[0], 0)
        self.assertEqual(self.records()[0]["path"], "destination")

    def test_unsupported_and_malformed_fail_before_mutation(self):
        cases = [
            ["clone", "--future=value", "remote", "repo"],
            ["clone", "--depth"], ["clone", "remote", "one", "two"],
            ["clone", "--separate-git-dir", str(self.base / "meta"), "remote", "repo"],
            ["init", "--separate-git-dir=meta", "repo"], ["init", "--future", "repo"],
            ["clone", "https://user:password@example.org/repo.git?token=secret#fragment"],
            ["clone", "ext::helper"], ["init", "."], ["init", ".context/new"],
        ]
        before = self.metadata.read_bytes()
        for args in cases:
            with self.subTest(args=args):
                self.assertNotEqual(self.invoke("-C", str(self.context), *args)[0], 0)
                self.assertEqual(self.metadata.read_bytes(), before)
        self.assertFalse(self.run_mock.called)
        self.assertFalse(self.sync_mock.called)

    def test_unknown_option_cannot_hide_absolute_destination(self):
        for args in (["clone", "--future", str(self.context / "repo"), "remote"],
                     ["init", "--future=" + str(self.context / "repo")]):
            self.assertNotEqual(self.invoke(*args)[0], 0)
        self.assertFalse(self.run_mock.called)

    def test_help_as_value_or_after_separator_does_not_bypass_protection(self):
        for args in (["clone", "--branch", "--help", "remote", "repo"],
                     ["clone", "--", "remote", "--help"]):
            with self.subTest(args=args):
                self.assertEqual(self.invoke("-C", str(self.context), *args)[0], 0)
                self.assertEqual(self.events[-2:], ["sync", "git"])

    def test_default_root_and_no_owner_fail_closed(self):
        with patch.dict(os.environ):
            del os.environ["CONTEXT_ROOT"]
            self.assertEqual(self.invoke("init", str(self.context / "repo"))[0], 0)
        self.assertNotEqual(self.invoke("init", str(self.root / "unowned"))[0], 0)
        self.assertNotEqual(self.invoke("init", str(self.root))[0], 0)

    def test_symlink_escape_destination_is_outside_passthrough(self):
        (self.context / "escape").symlink_to(self.base, target_is_directory=True)
        self.assertEqual(self.invoke("clone", "remote", str(self.context / "escape/repo"))[0], 0)
        self.assertFalse(self.sync_mock.called)

    def test_nested_context_and_overlapping_checkout_rejected(self):
        nested = self.context / "parent/nested"
        (nested / ".context").mkdir(parents=True)
        (nested / ".context/context.json").write_text('{"version": 1}')
        self.assertNotEqual(self.invoke("init", str(self.context / "parent"))[0], 0)
        repositories.register(self.root, self.context, self.context / "checkout")
        self.assertNotEqual(self.invoke("init", str(self.context / "checkout/child"))[0], 0)
        self.assertFalse(self.run_mock.called)

    def test_init_new_empty_and_registered_repository(self):
        self.assertEqual(self.invoke("init", str(self.context / "new"))[0], 0)
        empty = self.context / "empty"
        empty.mkdir()
        self.assertEqual(self.invoke("init", "--initial-branch=main", str(empty))[0], 0)
        (empty / ".git").mkdir()
        (empty / "tracked").write_text("keep")
        self.assertEqual(self.invoke("-C", str(empty), "init")[0], 0)
        self.assertEqual((empty / "tracked").read_text(), "keep")
        self.assertEqual(len(self.records()), 2)

    def test_nonempty_unregistered_and_registered_clone_rejected(self):
        directory = self.context / "ordinary"
        directory.mkdir()
        (directory / "shared").write_text("keep")
        for command in ("clone", "init"):
            args = [command, "remote"] if command == "clone" else [command]
            self.assertNotEqual(self.invoke(*args, str(directory))[0], 0)
        self.assertEqual(self.records(), [])
        repositories.register(self.root, self.context, directory)
        self.assertNotEqual(self.invoke("clone", "remote", str(directory))[0], 0)
        self.assertFalse(self.run_mock.called)

    def test_config_and_environment_location_overrides_rejected(self):
        for global_args in (["--git-dir=elsewhere"], ["--work-tree", "elsewhere"],
                            ["-ccore.worktree=elsewhere"], ["-cinclude.path=elsewhere"]):
            self.assertNotEqual(self.invoke(*global_args, "init", str(self.context / "repo"))[0], 0)
        with patch.dict(os.environ, {"GIT_DIR": "elsewhere"}):
            self.assertNotEqual(self.invoke("init", str(self.context / "repo"))[0], 0)
        with patch.dict(os.environ, {"GIT_DIR": str(self.context / "metadata")}):
            self.assertNotEqual(self.invoke("init")[0], 0)
        self.assertNotEqual(self.invoke("--git-dir", str(self.context / "metadata"), "init")[0], 0)
        self.assertFalse(self.run_mock.called)

    def test_registered_reinit_rejects_external_git_metadata(self):
        directory = self.context / "repo"
        directory.mkdir()
        external = self.base / "metadata"
        external.mkdir()
        repositories.register(self.root, self.context, directory)
        (directory / ".git").symlink_to(external, target_is_directory=True)
        self.assertNotEqual(self.invoke("init", str(directory))[0], 0)
        self.assertFalse(self.run_mock.called)

    def test_secret_url_scrubbed_and_not_in_errors(self):
        remote = "https://user:password@example.org/team/repo.git?token=secret#secret"
        self.assertEqual(self.invoke("clone", remote, str(self.context / "repo"))[0], 0)
        self.assertEqual(self.records()[0]["url"], "https://example.org/team/repo.git")
        self.run_mock.assert_called_once_with([os.environ["CONTEXT_REAL_GIT"], "clone", remote, str(self.context / "repo")])
        code, error = self.invoke("-C", str(self.context), "clone", remote)
        self.assertNotEqual(code, 0)
        self.assertNotIn("password", error)
        self.assertNotIn("secret", error)

    def test_failed_sync_retains_registration_without_running_git(self):
        self.sync_mock.side_effect = repositories.RepositoryError("Live protection unavailable")
        self.assertNotEqual(self.invoke("init", str(self.context / "repo"))[0], 0)
        self.assertEqual(self.records(), [{"path": "repo"}])
        self.assertFalse(self.run_mock.called)
        self.assertFalse((self.context / "repo").exists())

    def test_failed_clone_retains_ignore_and_registration(self):
        def sync(root, *, require_live):
            repositories._sync(root, offline=True)
        self.sync_mock.side_effect = sync
        self.run_mock.return_value = subprocess.CompletedProcess([], 128)
        self.run_mock.side_effect = None
        self.assertEqual(self.invoke("clone", "remote", str(self.context / "repo"))[0], 128)
        self.assertEqual(self.records(), [{"path": "repo"}])
        self.assertIn("/project/repo", (self.root / repositories.INCLUDE_FILE).read_text())

    def test_real_git_required_and_signal_exit_code(self):
        with patch.dict(os.environ, {"CONTEXT_REAL_GIT": "git"}):
            self.assertNotEqual(self.invoke("status")[0], 0)
        self.run_mock.side_effect = None
        self.run_mock.return_value = subprocess.CompletedProcess([], -15)
        self.assertEqual(self.invoke("status")[0], -15)

    def test_local_git_integration(self):
        realgit = "/run/current-system/sw/bin/git"
        if not os.access(realgit, os.X_OK):
            realgit = shutil.which("git")
        if not realgit or Path(realgit).resolve() == Path(wrapper.__file__).resolve():
            self.skipTest("Installed Git unavailable")
        with patch.object(wrapper.subprocess, "run", subprocess_run):
            def git(*args):
                return subprocess_run([realgit, *args], check=True, capture_output=True, text=True)
            source = self.base / "source"
            git("init", "-q", str(source))
            (source / "tracked").write_text("local integration\n")
            git("-C", str(source), "add", "tracked")
            git("-C", str(source), "-c", "user.name=Context Test", "-c", "user.email=test@example.invalid",
                "-c", "commit.gpgsign=false", "commit", "-qm", "Initial test commit")
            with patch.dict(os.environ, {"CONTEXT_REAL_GIT": realgit}):
                self.assertEqual(self.invoke("clone", str(source), str(self.context / "checkout"))[0], 0)
                self.assertEqual(self.invoke("init", str(self.context / "empty"))[0], 0)
                self.assertEqual(self.invoke("-C", str(self.context / "checkout"), "init")[0], 0)
            self.assertEqual(git("-C", str(self.context / "checkout"), "status", "--porcelain").stdout, "")
            self.assertEqual((self.context / "checkout/tracked").read_text(), "local integration\n")
            self.assertEqual(self.events, ["sync", "sync", "sync"])


subprocess_run = subprocess.run


if __name__ == "__main__":
    unittest.main()
