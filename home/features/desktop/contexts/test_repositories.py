import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import repositories as repos


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "sessions"
        self.root.mkdir()
        self.context = self.context_at("Projects/Alpha")
        environment = patch.dict(os.environ, {
            "HOME": str(self.base), "XDG_STATE_HOME": str(self.base / "state"),
            "SYNCTHING_CONFIG": str(self.base / "config.xml"),
            "SYNCTHING_URL": "http://127.0.0.1:9999",
        })
        environment.start()
        self.addCleanup(environment.stop)
        (self.base / "config.xml").write_text("<configuration><gui><apikey>private</apikey></gui></configuration>")
        self.ignores = ["!keep/**", "**/work", "**/.git", "// user comment"]
        self.folder_path = str(self.root)
        self.expanded = []
        self.calls = []
        self.bad_confirmation = False
        api = patch.object(repos.urllib.request, "urlopen", side_effect=self.api)
        api.start()
        self.addCleanup(api.stop)

    def context_at(self, relative, **extra):
        directory = self.root / relative
        (directory / ".context").mkdir(parents=True)
        self.write(directory, {"version": 1, "name": directory.name, "notes": "preserve", **extra})
        return directory

    def write(self, directory, data):
        (directory / ".context/context.json").write_text(json.dumps(data))

    def read(self):
        return json.loads((self.context / ".context/context.json").read_text())

    def api(self, request, timeout):
        self.calls.append(request)
        self.assertEqual(timeout, 5)
        self.assertEqual(request.get_header("X-api-key"), "private")
        if request.full_url.endswith("/rest/config/folders/sessions"):
            self.assertEqual(request.get_method(), "GET")
            return io.StringIO(json.dumps({"id": "sessions", "path": self.folder_path}))
        self.assertTrue(request.full_url.endswith("/rest/db/ignores?folder=sessions"))
        if request.data is not None:
            self.ignores = json.loads(request.data)["ignore"]
            lines = (self.root / repos.INCLUDE_FILE).read_text().splitlines()[1:]
            self.expanded = [pattern for line in lines if line for pattern in (line, line + "/**")]
        expanded = [] if self.bad_confirmation else self.expanded
        return io.StringIO(json.dumps({"ignore": self.ignores, "expanded": expanded}))

    def add(self, relative="source", url=None):
        destination = self.context / relative
        repos.register(self.root, self.context, destination, url)
        return destination

    def test_schema_and_lexical_paths(self):
        for value in ("", ".", "..", "/tmp/x", "a/../b", "a/./b", "a//b", "a/", ".git",
                      "a/.context/repo", "a/.hidden", " a", "a ", "a\nb", "a\rb", "a\tb", "a\x7fb", "a\ud800b"):
            with self.subTest(value=value), self.assertRaises(repos.RepositoryError):
                repos.repository_paths(self.context, {"version": 1, "repositories": [{"path": value}]})
        for data in ([], {}, {"version": True}, {"version": 2}, {"version": 1, "repositories": None},
                     {"version": 1, "repositories": [{}]},
                     {"version": 1, "repositories": [{"path": "repo", "url": None}]}):
            with self.subTest(data=data), self.assertRaises(repos.RepositoryError):
                repos.repository_paths(self.context, data)
        self.assertEqual(repos.repository_paths(self.context, {"version": 1, "working_directory": "work/Legacy"}), [])
        self.assertEqual(repos.repository_paths(self.context, {"version": 1, "repositories": [{"path": "work/A [b]*?{x,y}\\z"}]}),
                         [self.context / "work/A [b]*?{x,y}\\z"])

    def test_symlinks_and_overlaps(self):
        (self.context / "escape").symlink_to(self.base)
        for paths in (["escape/repo"], ["repo", "repo/child"], ["repo", "repo"]):
            with self.subTest(paths=paths), self.assertRaises(repos.RepositoryError):
                repos.repository_paths(self.context, {"version": 1, "repositories": [{"path": path} for path in paths]})
        (self.context / "alias").symlink_to(self.context / "target")
        self.assertEqual(repos.repository_paths(self.context, {"version": 1, "repositories": [{"path": "alias/missing"}]}),
                         [self.context / "alias/missing"])
        with self.assertRaises(repos.RepositoryError):
            repos.repository_paths(self.context, {"version": 1, "repositories": [{"path": "alias"}, {"path": "target"}]})

    def test_register_preserves_metadata_and_checkout(self):
        destination = self.add("work/Repo", "https://example.invalid/repo")
        destination.mkdir(parents=True)
        (destination / "keep").write_text("checkout contents")
        repos.register(self.root, self.context, destination)
        self.assertEqual(self.read()["repositories"], [{"path": "work/Repo", "url": "https://example.invalid/repo"}])
        repos.register(self.root, self.context, destination, "new-url")
        self.assertEqual(self.read()["repositories"], [{"path": "work/Repo", "url": "new-url"}])
        self.assertEqual(self.read()["notes"], "preserve")
        self.assertEqual((destination / "keep").read_text(), "checkout contents")
        with self.assertRaises(repos.RepositoryError):
            self.add("work/Repo/nested")

    def test_owner_and_nested_context_conflicts(self):
        nested = self.context_at("Projects/Alpha/work/Child")
        self.assertEqual(repos.owning_context(self.root, nested / "repo"), nested)
        self.assertIsNone(repos.owning_context(self.root, self.base / "elsewhere"))
        for destination in (self.context, self.context / "work", nested / "repo"):
            with self.subTest(destination=destination), self.assertRaises(repos.RepositoryError):
                repos.register(self.root, self.context, destination)
        with self.assertRaises(repos.RepositoryError):
            repos.owning_context(self.root, nested)
        (self.base / "cwd").symlink_to(nested)
        self.assertEqual(repos.owning_context(self.root, self.base / "cwd/missing/repo"), nested)
        with self.assertRaises(repos.RepositoryError):
            repos.repository_paths(self.context, {"version": 1, "repositories": [{"path": "work/Child/repo"}]})

    def test_walk_prunes_only_checkouts_hidden_and_git(self):
        destination = self.add("work/Repo")
        (destination / "deep/.context").mkdir(parents=True)
        (destination / "deep/.context/context.json").write_text("invalid")
        child = self.context_at("Projects/Alpha/work/Notebook", repositories=[{"path": "source"}])
        for hidden in (".git", ".hidden"):
            directory = self.context / hidden / "bad/.context"
            directory.mkdir(parents=True)
            (directory / "context.json").write_text("invalid")
        self.assertEqual(repos.registered(self.root), [
            {"context": self.context, "path": destination},
            {"context": child, "path": child / "source"},
        ])

    def test_exact_glob_escaping_and_live_order(self):
        self.add("work/A [b]*?{x,y}\\z", "https://user:secret@example.invalid/repo")
        original = list(self.ignores)
        result = repos.sync(self.root, require_live=True)
        pattern = "/Projects/Alpha/work/A \\[b\\]\\*\\?\\{x\\,y\\}\\\\z"
        self.assertEqual((self.root / repos.INCLUDE_FILE).read_text(), "#escape=\\\n" + pattern + "\n")
        self.assertTrue(result["live"])
        self.assertEqual(self.ignores, [repos.INCLUDE] + original)
        self.assertEqual([call.get_method() for call in self.calls], ["GET", "GET", "POST", "GET"])
        self.assertNotIn("secret", (self.root / repos.LEDGER_FILE).read_text())
        self.assertNotIn("secret", (self.root / repos.INCLUDE_FILE).read_text())

    def test_union_and_reload_when_only_include_changes(self):
        self.add("first")
        repos.sync(self.root, require_live=True)
        data = self.read()
        data["repositories"] = [{"path": "second"}]
        self.write(self.context, data)
        result = repos.sync(self.root, require_live=True)
        self.assertEqual(result["paths"], ["Projects/Alpha/first", "Projects/Alpha/second"])
        self.assertEqual(self.ignores.count(repos.INCLUDE), 1)
        self.assertEqual(len(self.calls), 8)
        data.pop("repositories")
        self.write(self.context, data)
        self.assertEqual(repos.sync(self.root)["paths"], result["paths"])

    def test_live_current_state_needs_only_synchronous_get(self):
        self.add()
        repos.sync(self.root, require_live=True)
        original = list(self.ignores)
        self.calls.clear()
        # Extra unrelated expanded patterns are valid after the managed prefix.
        self.expanded.append("/unrelated/**")
        for require_live in (False, True):
            self.assertTrue(repos.sync(self.root, require_live=require_live)["live"])
        self.assertEqual([call.get_method() for call in self.calls], ["GET", "GET", "GET", "GET"])
        self.assertTrue(self.calls[0].full_url.endswith("/rest/config/folders/sessions"))
        self.assertTrue(self.calls[1].full_url.endswith("/rest/db/ignores?folder=sessions"))
        self.assertEqual(self.ignores, original)

    def test_live_drift_triggers_post_and_confirmation(self):
        self.add()
        repos.sync(self.root, require_live=True)
        original = list(self.ignores)
        for drift in ("missing include", "reordered include", "stale expansion", "reordered expansion"):
            with self.subTest(drift=drift):
                if drift == "missing include":
                    self.ignores.remove(repos.INCLUDE)
                elif drift == "reordered include":
                    self.ignores = self.ignores[1:] + [repos.INCLUDE]
                elif drift == "stale expansion":
                    self.expanded = []
                else:
                    self.expanded.reverse()
                self.calls.clear()
                self.assertTrue(repos.sync(self.root, require_live=True)["live"])
                self.assertEqual([call.get_method() for call in self.calls], ["GET", "GET", "POST", "GET"])
                self.assertEqual(self.ignores, original)

    def test_live_root_mismatch_never_touches_ignores(self):
        self.add()
        self.folder_path = str(self.base / "different-root")
        original = list(self.ignores)
        for require_live in (True, False):
            self.calls.clear()
            if require_live:
                with self.assertRaises(repos.RepositoryError) as raised:
                    repos.sync(self.root, require_live=True)
                self.assertEqual(str(raised.exception), "Syncthing live exclusions not confirmed")
            else:
                self.assertFalse(repos.sync(self.root)["live"])
            self.assertEqual(len(self.calls), 1)
            self.assertTrue(self.calls[0].full_url.endswith("/rest/config/folders/sessions"))
            self.assertEqual(self.calls[0].get_method(), "GET")
            self.assertEqual(self.ignores, original)
            self.assertTrue((self.root / repos.INCLUDE_FILE).exists())
            self.assertTrue((self.root / repos.LEDGER_FILE).exists())

    def test_live_root_expands_home_and_resolves_local_paths(self):
        self.add()
        (self.base / "sessions-alias").symlink_to(self.root)
        for folder_path in ("~/sessions/../sessions", "~/sessions-alias", str(self.root)):
            with self.subTest(folder_path=folder_path):
                self.folder_path = folder_path
                self.assertTrue(repos.sync(self.root, require_live=True)["live"])

    def test_folder_config_failures_are_sanitized_and_never_post(self):
        self.add()
        original = list(self.ignores)
        for response in ('{}', '[]', '{"path":null}', '{"path":""}', '{"path":"sessions"}',
                         '{"path":"https://private.invalid/sessions"}',
                         '{"error":"private config details"}', 'not JSON'):
            with self.subTest(response=response):
                with patch.object(repos.urllib.request, "urlopen", return_value=io.StringIO(response)) as api:
                    with self.assertRaises(repos.RepositoryError) as raised:
                        repos.sync(self.root, require_live=True)
                self.assertEqual(str(raised.exception), "Syncthing live exclusions not confirmed")
                self.assertEqual(api.call_count, 1)
                self.assertEqual(api.call_args.args[0].get_method(), "GET")
                self.assertTrue(api.call_args.args[0].full_url.endswith("/rest/config/folders/sessions"))
                self.assertEqual(self.ignores, original)
        with patch.object(repos.urllib.request, "urlopen", side_effect=OSError("private API failure")) as api:
            self.assertFalse(repos.sync(self.root)["live"])
            self.assertEqual(api.call_count, 1)
            self.assertEqual(self.ignores, original)

    def test_malformed_metadata_preserves_both_files(self):
        self.add()
        repos.sync(self.root)
        previous = [(self.root / name).read_bytes() for name in (repos.INCLUDE_FILE, repos.LEDGER_FILE)]
        for invalid in ("{", json.dumps({"version": 1, "repositories": [{"path": "../escape"}]})):
            (self.context / ".context/context.json").write_text(invalid)
            with self.assertRaises(repos.RepositoryError):
                repos.sync(self.root)
            self.assertEqual(previous, [(self.root / name).read_bytes() for name in (repos.INCLUDE_FILE, repos.LEDGER_FILE)])

    def test_invalid_ledger_and_missing_ledger_fail_closed(self):
        self.add()
        repos.sync(self.root)
        previous = (self.root / repos.INCLUDE_FILE).read_bytes()
        ledger = self.root / repos.LEDGER_FILE
        ledger.write_text('{"version":1,"paths":["../unsafe"]}')
        with self.assertRaises(repos.RepositoryError):
            repos.sync(self.root)
        self.assertEqual((self.root / repos.INCLUDE_FILE).read_bytes(), previous)
        ledger.unlink()
        with self.assertRaises(repos.RepositoryError):
            repos.sync(self.root)

    def test_live_failure_retains_registration_and_generated_state(self):
        self.add()
        self.bad_confirmation = True
        with self.assertRaises(repos.RepositoryError):
            repos.sync(self.root, require_live=True)
        self.assertEqual(self.read()["repositories"], [{"path": "source"}])
        self.assertTrue((self.root / repos.INCLUDE_FILE).exists())
        self.assertFalse(repos.sync(self.root)["live"])
        with patch.object(repos.urllib.request, "urlopen", side_effect=OSError("secret URL")):
            with self.assertRaises(repos.RepositoryError) as raised:
                repos.sync(self.root, require_live=True)
            self.assertNotIn("secret", str(raised.exception))
            self.assertFalse(repos.sync(self.root)["live"])

    def test_confirmation_checks_include_and_order_not_only_patterns(self):
        self.add()
        original_api = self.api

        def broken(request, timeout):
            response = original_api(request, timeout)
            data = json.load(response)
            if len(self.calls) == 4:
                data["ignore"] = self.ignores[1:] + [repos.INCLUDE]
            return io.StringIO(json.dumps(data))

        with patch.object(repos.urllib.request, "urlopen", side_effect=broken):
            with self.assertRaises(repos.RepositoryError):
                repos.sync(self.root, require_live=True)

    def test_offline_cli_generates_without_stignore_or_api(self):
        self.add()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(repos.main(["sync", "--root", str(self.root), "--offline"]), 0)
        self.assertFalse(json.loads(output.getvalue())["live"])
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / ".stignore").exists())
        self.assertIn(repos.INCLUDE_FILE, repos.STATIC_BASE)
        self.assertIn(repos.LEDGER_FILE, repos.STATIC_BASE)

    def test_contained_alias_protects_and_prunes_physical_checkout(self):
        target = self.context / "physical"
        (self.context / "alias").symlink_to(target)
        data = self.read()
        data["repositories"] = [{"path": "alias"}]
        self.write(self.context, data)
        (target / "deep/.context").mkdir(parents=True)
        (target / "deep/.context/context.json").write_text("not context metadata")
        self.assertEqual(repos.sync(self.root, require_live=True)["paths"],
                         ["Projects/Alpha/alias", "Projects/Alpha/physical"])
        repos.register(self.root, self.context, self.context / "alias", "updated")
        self.assertEqual(self.read()["repositories"], [{"path": "alias", "url": "updated"}])
        (self.context / "notes-alias").symlink_to(self.context / ".context/notes")
        with self.assertRaises(repos.RepositoryError):
            repos.repository_paths(self.context, {"version": 1, "repositories": [{"path": "notes-alias"}]})

    def test_watch_retries_after_failure_without_compositor(self):
        with patch.object(repos, "sync", side_effect=[repos.RepositoryError("failed"), {}]) as sync:
            with patch.object(repos.time, "sleep", side_effect=[None, KeyboardInterrupt]) as sleep:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(KeyboardInterrupt):
                    repos.main(["watch", "--root", str(self.root)])
        self.assertEqual(sync.call_count, 2)
        sync.assert_called_with(self.root, require_live=True)
        self.assertEqual(sleep.call_args_list[0].args, (1,))

    def test_api_error_and_malformed_responses_fail_closed(self):
        self.add()
        for response in ('{"error":"private details"}', '{}', '[]', '{"ignore":[1]}', 'not JSON'):
            with self.subTest(response=response):
                def broken(request, timeout):
                    if request.full_url.endswith("/rest/config/folders/sessions"):
                        return self.api(request, timeout)
                    return io.StringIO(response)

                with patch.object(repos.urllib.request, "urlopen", side_effect=broken):
                    with self.assertRaises(repos.RepositoryError) as raised:
                        repos.sync(self.root, require_live=True)
                self.assertNotIn("private", str(raised.exception))

    def test_local_state_symlinks_never_overwrite_other_files(self):
        self.add()
        unrelated = self.base / "untouched"
        unrelated.write_text("keep")
        ledger = self.root / repos.LEDGER_FILE
        ledger.symlink_to(unrelated)
        with self.assertRaises(repos.RepositoryError):
            repos.sync(self.root)
        ledger.unlink()
        (self.root / repos.INCLUDE_FILE).symlink_to(unrelated)
        with self.assertRaises(repos.RepositoryError):
            repos.sync(self.root)
        self.assertEqual(unrelated.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
