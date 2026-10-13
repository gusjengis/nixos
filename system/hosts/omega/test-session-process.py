"""Session processor regression fixtures; no network or live vault access."""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location("sessions", HERE / "session-process.py")
sessions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sessions)


class ProcessorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.vault = self.root / "vault"
        self.vault.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        self.ex = sessions.load_extract(HERE / "note-extract.py")
        self.args = argparse.Namespace(vault=self.vault, state=self.state,
            extract_module=HERE / "note-extract.py", model="fixture", ollama_url="unused",
            review_context="Note processing", limit=5, session=None, no_model=False)
        self.body = "## User 2026-10-01T12:00:00Z ^msg-one\nFix notes.\n\n### Tool bash ^part-one\nTests pass.\n\n## Assistant 2026-10-01T12:01:00Z ^msg-two\nImplemented.\n"
        self.export()
        self.note("Projects/Obsidian second brain", {"type": "project"}, "Project")
        self.note("Thoughts/Fix notes", {"types": ["insight"], "status": "todo",
            "contexts": ["[[Contexts/Note processing]]"]}, "Fix notes")
        self.answer = {"summary": {"text": "Notes fixed", "evidence": ["msg-two"]},
            "decisions": [], "verified": [{"text": "Tests passed", "evidence": ["part-one"]}],
            "unresolved": [], "proposed_closures": [{"thought": "Thoughts/Fix notes.md",
                "outcome": "implemented", "reason": "Tests pass", "evidence": ["part-one"]}],
            "proposed_new_thoughts": [{"text": "Check sync", "reason": "Follow-up",
                "evidence": ["msg-one"]}], "project_links": ["Projects/Obsidian second brain.md"]}
        self.calls = []

    def note(self, name, meta, body):
        path = self.vault / f"{name}.md"
        self.ex.write_atomic(self.vault, path, self.ex.join_note(meta, body))
        return path

    def export(self, device="alpha", updated="2026-10-01T12:01:00Z", parent=None, key="abc123", projects=None,
               title=None, checkout="/etc/nixos", remote="https://github.com/example/nixos"):
        return self.note(f"Sessions/OpenCode/Transcripts/{device}/{key}", {
            "type": "opencode-transcript", "schema": 1, "session-key": key,
            "session-id": "session-original", "parent-session-id": parent,
            "device": device, "title": title or device, "created": "2026-10-01T12:00:00Z",
            "updated": updated, "repository-id": "a" * 64, "repository-name": "nixos",
            "repository-remote": remote, "checkout": checkout,
            "projects": projects or [], "revision": hashlib.sha256(self.body.encode()).hexdigest(),
        }, self.body)

    def call(self, url, model, payload):
        self.calls.append(payload)
        return copy.deepcopy(self.answer)

    def run_processor(self):
        return sessions.process(self.args, self.call)

    def session_path(self, key="abc123"):
        matches = [p for p in (self.vault / "Sessions/OpenCode").glob("*.md")
                   if self.ex.split_note(p.read_text())[0].get("session-key") == key]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_graph_dedup_and_review_only(self):
        thought = (self.vault / "Thoughts/Fix notes.md").read_bytes()
        self.note("Thoughts/Unrelated idea", {"types": ["idea"],
                  "contexts": ["[[Contexts/Note processing]]"]}, "Unrelated possibility")
        self.export("beta", "2026-10-02T12:00:00Z", projects=["[[Projects/Obsidian second brain]]"])
        self.assertEqual(self.run_processor(), 0)
        session = self.session_path()
        meta, body = self.ex.split_note(session.read_text())
        self.assertEqual(meta["title"], "beta")
        self.assertEqual(len(meta["transcripts"]), 2)
        self.assertEqual(meta["ran-in"], "[[Repositories/nixos--aaaaaaaaaaaaaaaa]]")
        self.assertEqual(meta["concerns"], ["[[Projects/Obsidian second brain]]"])
        self.assertNotIn("/etc/nixos", body)
        self.assertEqual((self.vault / "Thoughts/Fix notes.md").read_bytes(), thought)
        review = (self.vault / "Sessions/OpenCode/Reviews/abc123.md").read_text()
        self.assertIn("#^part-one", review)
        self.assertIn("Proposed New Thoughts", review)
        self.assertIn("Session: " + self.ex.link(sessions.rel(self.vault, session)), review)
        self.assertIn("Repository: [[Repositories/nixos--aaaaaaaaaaaaaaaa]]", review)
        self.assertNotIn("[[Thoughts/Unrelated idea]]", review)
        self.assertEqual(len(list((self.vault / "Sessions/OpenCode").glob("*.md"))), 1)

    def test_cache_and_context_edit(self):
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 1)
        self.export("beta", updated="2026-10-02T12:00:00Z")
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 1)
        path = self.vault / "Thoughts/Fix notes.md"
        self.ex.write_atomic(self.vault, path, path.read_text() + "\nHuman edit\n")
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 2)

    def test_failure_retains_review_and_cache_then_retries(self):
        self.run_processor()
        review = self.vault / "Sessions/OpenCode/Reviews/abc123.md"
        cache = self.state / "abc123.json"
        before = (review.read_bytes(), cache.read_bytes())
        self.body += "\n## User 2026-10-03T12:00:00Z ^msg-three\nMore work\n"
        self.export(updated="2026-10-03T12:00:00Z")
        self.answer["proposed_closures"][0]["evidence"] = ["invented-id"]
        self.assertEqual(self.run_processor(), 1)
        self.assertEqual(cache.read_bytes(), before[1])
        before_meta, before_body = self.ex.split_note(before[0].decode())
        pending_meta, pending_body = self.ex.split_note(review.read_text())
        start, finish = sessions.section_bounds(before_body, "review")
        self.assertIn(before_body[start:finish], pending_body)
        self.assertEqual(pending_meta["reviewed-revision"], before_meta["reviewed-revision"])
        self.assertEqual(pending_meta["current-review-state"], "pending")
        self.answer["proposed_closures"][0]["evidence"] = ["msg-three"]
        self.assertEqual(self.run_processor(), 0)
        self.assertNotEqual(cache.read_bytes(), before[1])

    def test_invalid_links_missing_evidence(self):
        for change in (lambda a: a.update(project_links=["Projects/Unknown"]),
                       lambda a: a["summary"].update(evidence=[]),
                       lambda a: a["proposed_closures"][0].update(thought="../secret")):
            with self.subTest(change=change):
                answer = copy.deepcopy(self.answer)
                change(answer)
                with self.assertRaises(ValueError):
                    sessions.validate(answer, {"msg-one", "msg-two", "part-one"},
                        {"Thoughts/Fix notes.md"}, {"Projects/Obsidian second brain.md"})

    def test_annotations_and_repository_identity(self):
        self.run_processor()
        repo = self.vault / "Repositories/nixos--aaaaaaaaaaaaaaaa.md"
        session = self.session_path()
        review = self.vault / "Sessions/OpenCode/Reviews/abc123.md"
        for path in (repo, session, review):
            meta, body = self.ex.split_note(path.read_text())
            meta["human-field"] = "keep"
            self.ex.write_atomic(self.vault, path, self.ex.join_note(meta, "Human annotation\n" + body + "\nAfter block\n"))
        self.body += "\n## User now ^msg-extra\nContinue\n"
        path = self.export(updated="2026-10-04T12:00:00Z")
        meta, body = self.ex.split_note(path.read_text())
        meta["repository-name"] = "renamed"
        self.ex.write_atomic(self.vault, path, self.ex.join_note(meta, body))
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(list((self.vault / "Repositories").glob("*.md"))), 1)
        for path in (repo, session, review):
            meta, body = self.ex.split_note(path.read_text())
            self.assertEqual(meta["human-field"], "keep")
            self.assertIn("Human annotation", body)
            self.assertIn("After block", body)

    def test_children_graph_only_and_no_model(self):
        self.export(parent="parent", key="child")
        self.args.no_model = True
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(self.calls, [])
        meta, _ = self.ex.split_note(self.session_path().read_text())
        self.assertEqual(meta["concerns"], [])
        self.args.no_model = False
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.session_path("child").exists())
        self.assertFalse((self.vault / "Sessions/OpenCode/Reviews/child.md").exists())

    def test_bound_evidence_and_partial_warning(self):
        self.body += "\n## User later ^omitted-id\n" + "x" * sessions.BODY_LIMIT
        self.export()
        self.assertEqual(self.run_processor(), 0)
        self.assertGreater(self.calls[0]["omitted_transcript_chars"], 0)
        self.assertNotIn("omitted-id", self.calls[0]["transcript"])
        self.assertIn("WARNING: Partial coverage", (self.vault / "Sessions/OpenCode/Reviews/abc123.md").read_text())
        with self.assertRaises(ValueError):
            answer = copy.deepcopy(self.answer)
            answer["summary"]["evidence"] = ["omitted-id"]
            sessions.validate(answer, sessions.supplied_body(self.body)[1],
                              {"Thoughts/Fix notes.md"}, {"Projects/Obsidian second brain.md"})

    def test_candidate_filters_and_limit(self):
        for name, fields in (("Done", {"status": "dealt-with"}), ("Orphan", {"orphaned": True}),
                             ("Noise", {"types": ["noise"]}), ("Other", {"contexts": []})):
            self.note(f"Thoughts/{name}", {"types": ["log"], "contexts": ["[[Contexts/Note processing]]"], **fields}, name)
        self.export(key="second")
        self.args.limit = 1
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(list(self.calls[0]["candidate_thoughts"]), ["Thoughts/Fix notes.md"])
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 2)

    def test_newer_source_invalidates_cache(self):
        path = self.vault / "Thoughts/Fix notes.md"
        meta, body = self.ex.split_note(path.read_text())
        meta["source"] = ["[[Normalized/New capture]]"]
        self.ex.write_atomic(self.vault, path, self.ex.join_note(meta, body))
        self.note("Normalized/New capture", {"created": "2026-10-02T12:00:00Z"}, "New information")
        self.assertEqual(self.run_processor(), 0)
        self.assertIn("Normalized/New capture", self.calls[0]["newer_sources"])
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 1)
        self.note("Normalized/New capture", {"created": "2026-10-02T12:00:00Z"}, "Changed information")
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 2)

    def test_tie_break_and_explicit_child_selection(self):
        self.export("zeta")
        self.args.no_model = True
        self.assertEqual(self.run_processor(), 0)
        meta, _ = self.ex.split_note(self.session_path().read_text())
        self.assertEqual(meta["title"], "zeta")
        self.export(parent="parent", key="child")
        self.args.no_model = False
        self.args.session = ["child"]
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue((self.vault / "Sessions/OpenCode/Reviews/child.md").exists())

    def test_total_input_byte_bound(self):
        payload = {"transcript": self.body + "## User later ^large\n" + "x" * 40000,
            "candidate_thoughts": {"Thoughts/Large": "x" * 24000}, "newer_sources": {},
            "existing_projects": [], "omitted_transcript_chars": 0,
            "omitted_thoughts": 0, "omitted_sources": 0, "omitted_projects": 0}
        ids = sessions.bound_payload(payload)
        self.assertNotIn("large", ids)
        self.assertGreater(payload["omitted_thoughts"], 0)
        self.assertGreater(payload["omitted_transcript_chars"], 0)

    def test_readable_filename_survives_title_changes_and_legacy_note(self):
        self.export(title="Fix session graph / labels", key="abcdef0123456789")
        self.args.no_model = True
        self.assertEqual(self.run_processor(), 0)
        path = self.session_path("abcdef0123456789")
        self.assertEqual(path.name, "Fix session graph labels--abcdef012345.md")
        self.export(title="Completely different title", key="abcdef0123456789",
                    updated="2026-10-04T12:00:00Z")
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(self.session_path("abcdef0123456789"), path)
        self.assertEqual(self.ex.split_note(path.read_text())[0]["title"], "Completely different title")
        legacy = self.note("Sessions/OpenCode/old-hash", {"session-key": "legacy"}, "Human annotation")
        self.export(key="legacy", title="New readable title")
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(self.session_path("legacy"), legacy)
        self.assertIn("Human annotation", legacy.read_text())

    def test_repository_aggregates_checkouts_projects_and_preserves_concerns(self):
        self.note("Projects/Other project", {}, "Other")
        outside = self.root / "outside.md"
        outside.write_text("Outside")
        (self.vault / "Projects/External.md").symlink_to(outside)
        invalid = ["[[Projects/Absent]]", "[[Projects/../../outside]]", "[[https://example.com]]",
                   "[[Projects/External]]", "[[/Projects/Other project]]"]
        self.export(projects=["[[Projects/Obsidian second brain]]", *invalid])
        self.export("beta", key="another", checkout="/work/nixos", updated="2026-10-03T12:00:00Z",
                    projects=["[[Projects/Other project.md]]"], remote="https://github.com/example/new-name")
        self.export("alpha", key="third", checkout="/home/user/nixos")
        self.args.no_model = True
        self.args.session = ["abc123"]
        self.assertEqual(self.run_processor(), 0)
        repo = self.vault / "Repositories/nixos--aaaaaaaaaaaaaaaa.md"
        meta, body = self.ex.split_note(repo.read_text())
        self.assertEqual(meta["checkouts"], [{"device": "alpha", "path": "/etc/nixos"},
            {"device": "alpha", "path": "/home/user/nixos"}, {"device": "beta", "path": "/work/nixos"}])
        self.assertEqual(meta["repository-remote"], "https://github.com/example/new-name")
        self.assertEqual(meta["concerns"], ["[[Projects/Obsidian second brain]]", "[[Projects/Other project]]"])
        session_meta, _ = self.ex.split_note(self.session_path().read_text())
        self.assertEqual(session_meta["concerns"], ["[[Projects/Obsidian second brain]]"])
        meta["concerns"].append("[[Entities/Human concern]]")
        self.ex.write_atomic(self.vault, repo, self.ex.join_note(meta, "Human annotation\n" + body))
        self.assertEqual(self.run_processor(), 0)
        meta, body = self.ex.split_note(repo.read_text())
        self.assertIn("[[Entities/Human concern]]", meta["concerns"])
        self.assertIn("Human annotation", body)

    def test_latest_blocks_skip_oversized_tool_and_validate_supplied_ids_only(self):
        self.body = ("## User earlier ^old-intent\n" + "o" * 18000 + "\n"
            + "### Tool bash ^oversized-output\n" + "x" * 70000 + "\n"
            + "## User later ^msg-one\n" + "u" * 8000 + "\n"
            + "### Tool bash ^part-one\nActual final test result\n"
            + "## Assistant latest ^msg-two\nClaimed complete\n")
        self.export()
        self.assertEqual(self.run_processor(), 0)
        payload = self.calls[0]
        transcript = payload["transcript"]
        self.assertFalse("old-intent" in transcript)
        self.assertFalse("oversized-output" in transcript)
        self.assertLess(transcript.index("msg-one"), transcript.index("part-one"))
        self.assertLess(transcript.index("part-one"), transcript.index("msg-two"))
        self.assertEqual(payload["omitted_transcript_chars"], len(self.body) - len(transcript))
        for bad_id in ("old-intent", "oversized-output"):
            answer = copy.deepcopy(self.answer)
            answer["summary"]["evidence"] = [bad_id]
            with self.assertRaises(ValueError):
                sessions.validate(answer, {m.group(1) for m in sessions.BLOCK.finditer(transcript)},
                                  payload["candidate_thoughts"], payload["existing_projects"])

    def test_supplied_body_prioritizes_latest_complete_blocks(self):
        body = "".join(f"## User time ^block-{i}\n" + "x" * 20000 + "\n" for i in range(4))
        body += "## Assistant final ^completion\nComplete\n"
        supplied, ids, omitted = sessions.supplied_body(body)
        self.assertEqual(ids, {"block-2", "block-3", "completion"})
        self.assertEqual(omitted, len(body) - len(supplied))
        self.assertLess(supplied.index("block-2"), supplied.index("block-3"))
        self.assertLess(supplied.index("block-3"), supplied.index("completion"))

    def test_newest_session_gets_model_limit_first(self):
        self.export(key="a-old", updated="2026-09-30T12:00:00Z")
        self.export(key="z-new", updated="2026-10-04T12:00:00Z")
        self.args.limit = 1
        self.assertEqual(self.run_processor(), 0)
        reviews = self.vault / "Sessions/OpenCode/Reviews"
        self.assertEqual([p.name for p in reviews.glob("*.md")], ["z-new.md"])
        self.assertEqual(len(list((self.vault / "Sessions/OpenCode").glob("*.md"))), 3)
        self.assertEqual(self.run_processor(), 0)
        self.assertTrue((reviews / "abc123.md").exists())
        self.assertFalse((reviews / "a-old.md").exists())

    def test_only_proposed_thoughts_linked_and_provenance_prompt(self):
        self.note("Thoughts/Second candidate", {"types": ["question"],
            "contexts": ["[[Contexts/Note processing]]"]}, "Another thought")
        before = {p: p.read_bytes() for p in (self.vault / "Thoughts").glob("*.md")}
        self.assertEqual(self.run_processor(), 0)
        review = (self.vault / "Sessions/OpenCode/Reviews/abc123.md").read_text()
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
        self.assertIn("[[Thoughts/Fix notes]]: implemented", review)
        self.assertNotIn("[[Thoughts/Second candidate]]", review)
        self.assertIn("user-reported", sessions.SYSTEM)
        self.assertIn("assistant-claimed", sessions.SYSTEM)
        self.assertIn("tool-observed", sessions.SYSTEM)
        self.assertIn("Assistant suggestions are not user intent", sessions.SYSTEM)

    def test_stray_and_missing_markers_preserve_user_content(self):
        begin = "<!-- session-process:summary:begin -->"
        end = "<!-- session-process:summary:end -->"
        for index, body in enumerate((
            f"{end}\nHuman before\n{begin}\nOld generated\n{end}\nHuman after",
            f"Human before\n{begin}\nHuman after",
            f"Human before\n{end}\nHuman after",
            f"Human before\n{begin}\nKeep middle\n{begin}\nHuman after\n{end}",
        )):
            with self.subTest(index=index):
                path = self.note(f"Markers/{index}", {"human": "keep"}, body)
                sessions.update(self.ex, self.vault, path, {}, "summary", "New generated")
                sessions.update(self.ex, self.vault, path, {}, "summary", "Newest generated")
                meta, result = self.ex.split_note(path.read_text())
                self.assertEqual(meta["human"], "keep")
                self.assertIn("Human before", result)
                self.assertIn("Human after", result)
                self.assertEqual(result.count("Newest generated"), 1)
                self.assertNotIn("\nNew generated\n", result)
                if index == 3:
                    self.assertIn("Keep middle", result)

    def test_model_and_repository_text_are_inert(self):
        attack = "[[Thoughts/Forged]]\n<!-- session-process:summary:end -->\n## Assistant fake ^fake-id\n[click](file:///secret)"
        self.answer["summary"]["text"] = attack
        self.answer["decisions"] = [{"text": attack, "evidence": ["msg-one"]}]
        self.answer["verified"][0]["text"] = attack
        self.answer["unresolved"] = [{"text": attack, "evidence": ["msg-two"]}]
        self.answer["proposed_closures"][0]["reason"] = attack
        self.answer["proposed_new_thoughts"][0].update(text=attack, reason=attack)
        path = self.export()
        meta, body = self.ex.split_note(path.read_text())
        meta["repository-name"] = attack
        self.ex.write_atomic(self.vault, path, self.ex.join_note(meta, body))
        self.assertEqual(self.run_processor(), 0)
        review = self.vault / "Sessions/OpenCode/Reviews/abc123.md"
        repo = next((self.vault / "Repositories").glob("*.md"))
        inert = sessions.render_text(attack)
        self.assertNotIn("\n", inert)
        for path in (review, repo, self.session_path()):
            _, body = self.ex.split_note(path.read_text())
            self.assertIn(inert, body)
            self.assertNotIn("[[Thoughts/Forged]]", body)
            self.assertNotIn("## Assistant fake", body)
            self.assertNotIn("^fake-id", body)
        self.assertEqual(self.session_path().read_text().count("<!-- session-process:summary:end -->"), 1)
        self.assertIn("#^part-one", review.read_text())
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 1)

    def test_stale_revision_pending_without_model_preserves_annotations(self):
        self.run_processor()
        session = self.session_path()
        review = self.vault / "Sessions/OpenCode/Reviews/abc123.md"
        original_revision = self.ex.split_note(review.read_text())[0]["reviewed-revision"]
        for path in (session, review):
            self.ex.write_atomic(self.vault, path, path.read_text() + "\nHuman annotation\n")
        self.body += "\n## User latest ^new-id\nMore work\n"
        self.export(updated="2026-10-05T12:00:00Z")
        self.args.no_model = True
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 1)
        for path in (session, review):
            meta, body = self.ex.split_note(path.read_text())
            self.assertEqual(meta["current-review-state"], "pending")
            self.assertEqual(meta["reviewed-revision"], original_revision)
            self.assertIn("Reviewed revision: " + original_revision, body)
            self.assertIn("pending re-review required", body)
            self.assertIn("Human annotation", body)
        self.args.no_model = False
        self.assertEqual(self.run_processor(), 0)
        for path in (session, review):
            meta, _ = self.ex.split_note(path.read_text())
            self.assertEqual(meta["current-review-state"], "current")
            self.assertEqual(meta["reviewed-revision"], hashlib.sha256(self.body.encode()).hexdigest())

    def test_input_changes_mark_pending_before_limit_or_failed_call(self):
        self.run_processor()
        review = self.vault / "Sessions/OpenCode/Reviews/abc123.md"
        prior = self.ex.split_note(review.read_text())[0]
        thought = self.vault / "Thoughts/Fix notes.md"
        self.ex.write_atomic(self.vault, thought, thought.read_text() + "\nChanged context\n")
        self.args.limit = 0
        self.assertEqual(self.run_processor(), 0)
        pending, _ = self.ex.split_note(review.read_text())
        self.assertEqual(pending["current-review-state"], "pending")
        self.assertEqual(pending["input-fingerprint"], prior["input-fingerprint"])
        self.assertNotEqual(pending["current-input-fingerprint"], prior["input-fingerprint"])
        self.args.limit = 5
        def fail(url, model, payload):
            self.assertEqual(self.ex.split_note(review.read_text())[0]["current-review-state"], "pending")
            raise RuntimeError("secret transport error")
        self.assertEqual(sessions.process(self.args, fail), 1)
        self.assertEqual(self.ex.split_note(self.session_path().read_text())[0]["current-review-state"], "pending")
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(self.ex.split_note(review.read_text())[0]["current-review-state"], "current")

    def test_deleted_or_broken_review_summary_bypasses_cache(self):
        self.run_processor()
        review = self.vault / "Sessions/OpenCode/Reviews/abc123.md"
        review.unlink()
        self.assertEqual(self.run_processor(), 0)
        self.assertTrue(review.exists())
        self.assertEqual(len(self.calls), 2)
        session = self.session_path()
        self.ex.write_atomic(self.vault, session, session.read_text().replace(
            "<!-- session-process:summary:end -->", "Human annotation"))
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 3)
        self.assertIn("Human annotation", session.read_text())
        self.assertIsNotNone(sessions.section_bounds(self.ex.split_note(session.read_text())[1], "summary"))
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 3)

    def test_export_filename_device_and_revision_integrity(self):
        for field, value in (("session-key", "wrong-key"), ("device", "wrong-device"),
                             ("revision", "0" * 64)):
            with self.subTest(field=field):
                path = self.export()
                meta, body = self.ex.split_note(path.read_text())
                meta[field] = value
                self.ex.write_atomic(self.vault, path, self.ex.join_note(meta, body))
                self.assertEqual(self.run_processor(), 1)
                self.assertEqual(self.calls, [])
                self.assertEqual(list((self.vault / "Sessions/OpenCode").glob("*.md")), [])

    def test_compact_twenty_two_candidates_keep_huge_session_evidence(self):
        first = self.vault / "Thoughts/Fix notes.md"
        meta, _ = self.ex.split_note(first.read_text())
        meta.update(id="first", captured="2026-10-01T12:00:00Z",
                    source=["[[Normalized/Supplement]]"])
        noisy_fields = {"score": "0.9 " * 1000, "tags": ["irrelevant"] * 100,
                        "depends-on": ["[[Thoughts/Other]]"] * 200,
                        "score-parts": {"facet": "scoring payload " * 300}}
        self.note("Thoughts/Fix notes", {**meta, **noisy_fields},
                  "Preserve orphaned extraction records and verify repository indexing.")
        for i in range(21):
            self.note(f"Thoughts/Extraction orphan preservation {i}", {
                "id": f"candidate-{i}", "types": ["requirement"], "status": "todo",
                "captured": "2026-10-01T12:00:00Z", "source": ["[[Normalized/Supplement]]"],
                "contexts": ["[[Contexts/Note processing]]"], **noisy_fields,
            }, "Preserve orphaned extraction records and verify repository indexing.")
        self.note("Normalized/Supplement", {"created": "2026-10-05T12:00:00Z", **noisy_fields},
                  "Supplemental context " * 120)
        self.body = ("## User start ^msg-one\nFix notes. Preserve orphaned extraction records.\n"
                     "### Tool bash ^part-one\nRepository indexing and orphaned extraction tests pass.\n"
                     "## Assistant earlier ^early-completion\nOrphaned extraction preservation implemented and repository indexing verified.\n")
        self.body += "".join(f"### Tool bash ^noise-{i}\n" + "unrelated terminal output " * 115 + "\n"
                             for i in range(200))
        self.body += "## Assistant final ^msg-two\nAll requested changes delivered.\n"
        self.export()
        before = {p: p.read_bytes() for p in (self.vault / "Thoughts").glob("*.md")}
        compact, omitted, hashes = sessions.candidates(self.ex, self.vault, "Note processing")
        self.assertEqual((len(compact), omitted, len(hashes)), (22, 0, 22))
        for thought in compact.values():
            self.assertEqual(set(thought), {"id", "types", "status", "captured", "source", "body"})
        self.assertEqual(self.run_processor(), 0)
        payload = self.calls[0]
        self.assertEqual(len(payload["candidate_thoughts"]), 22)
        self.assertEqual(payload["omitted_thoughts"], 0)
        self.assertGreaterEqual(len(payload["transcript"].encode()), sessions.TRANSCRIPT_BYTES)
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode()), sessions.INPUT_BYTES)
        self.assertIn("^early-completion", payload["transcript"])
        self.assertIn("^msg-two", payload["transcript"])
        self.assertGreater(payload["omitted_sources"], 0)
        self.assertEqual(payload["omitted_transcript_chars"], len(self.body) - len(payload["transcript"]))
        review = (self.vault / "Sessions/OpenCode/Reviews/abc123.md").read_text()
        self.assertIn("## Evidence Summary", review)
        self.assertIn("WARNING: Partial coverage", review)
        self.assertIn("## Evidence Summary", self.session_path().read_text())
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 1)
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)
        meta, body = self.ex.split_note(first.read_text())
        meta["score"] = "new scorer value"
        self.ex.write_atomic(self.vault, first, self.ex.join_note(meta, body))
        self.assertEqual(self.run_processor(), 0)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0]["candidate_thoughts"], self.calls[1]["candidate_thoughts"])

    def test_sources_are_compact_and_dropped_before_evidence(self):
        thought = self.vault / "Thoughts/Fix notes.md"
        meta, body = self.ex.split_note(thought.read_text())
        meta["source"] = ["[[Normalized/Newer]]"]
        self.ex.write_atomic(self.vault, thought, self.ex.join_note(meta, body))
        self.note("Normalized/Newer", {"created": "2026-10-05T12:00:00Z",
            "tags": ["noise"] * 1000, "score": "noise" * 5000}, "Durable newer context")
        self.assertEqual(self.run_processor(), 0)
        source = self.calls[0]["newer_sources"]["Normalized/Newer"]
        self.assertEqual(source, {"created": "2026-10-05T12:00:00Z", "body": "Durable newer context"})
        transcript = "".join(f"## User time ^block-{i}\n" + "x" * 2000 + "\n" for i in range(8))
        transcript += "## Assistant final ^completion\nFinished.\n"
        payload = {"transcript": transcript, "candidate_thoughts": {},
            "newer_sources": {"Normalized/Large": {"body": "x" * 10000}},
            "existing_projects": [], "omitted_transcript_chars": 0,
            "omitted_thoughts": 0, "omitted_sources": 0, "omitted_projects": 0}
        ids = sessions.bound_payload(payload)
        self.assertEqual(payload["transcript"], transcript)
        self.assertEqual(payload["omitted_transcript_chars"], 0)
        self.assertEqual(payload["omitted_sources"], 1)
        self.assertIn("completion", ids)

    def test_relevant_earlier_completion_and_terminal_report_survive(self):
        query = ("Embedding metadata migration", "Embedding metadata migration preserves old vectors.")
        body = "## Assistant early ^relevant\nEmbedding metadata migration preserves old vectors: implemented.\n"
        body += "### Tool bash ^giant\nEmbedding metadata migration " + "x" * 18000 + "\n"
        body += "".join(f"### Tool bash ^noise-{i}\n" + "unrelated output " * 200 + "\n" for i in range(40))
        body += "## Assistant final ^completion\nAll requested changes delivered.\n"
        supplied, _, omitted = sessions.supplied_body(body, [query])
        payload = {"transcript": supplied, "candidate_thoughts": {}, "newer_sources": {},
            "existing_projects": [], "omitted_transcript_chars": omitted,
            "omitted_thoughts": 0, "omitted_sources": 0, "omitted_projects": 0}
        ids = sessions.bound_payload(payload, [query])
        self.assertIn("relevant", ids)
        self.assertIn("completion", ids)
        self.assertLess(payload["transcript"].index("^relevant"), payload["transcript"].index("^completion"))
        self.assertEqual(payload["omitted_transcript_chars"], len(body) - len(payload["transcript"]))
        ranked = sessions.evidence_blocks(body, [query])
        self.assertGreater(ranked[0][2], ranked[1][2])
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode()), sessions.INPUT_BYTES)
        self.assertEqual(ids, {m.group(1) for m in sessions.BLOCK.finditer(payload["transcript"])})

    def test_new_proposals_capped_and_assistant_only_uncertain(self):
        answer = copy.deepcopy(self.answer)
        answer["proposed_new_thoughts"] *= 4
        with self.assertRaisesRegex(ValueError, "too many new thoughts"):
            sessions.validate(answer, {"msg-one", "msg-two", "part-one"},
                {"Thoughts/Fix notes.md"}, {"Projects/Obsidian second brain.md"})
        answer = copy.deepcopy(self.answer)
        answer["proposed_new_thoughts"][0]["evidence"] = ["msg-two"]
        with self.assertRaisesRegex(ValueError, "uncertain context"):
            sessions.validate(answer, {"msg-one", "msg-two", "part-one"},
                {"Thoughts/Fix notes.md"}, {"Projects/Obsidian second brain.md"}, {"msg-two"})
        answer["proposed_new_thoughts"][0].update(text="Uncertain context: sync may need investigation",
                                               reason="Assistant-only diagnostic; no adopted user intent")
        sessions.validate(answer, {"msg-one", "msg-two", "part-one"},
            {"Thoughts/Fix notes.md"}, {"Projects/Obsidian second brain.md"}, {"msg-two"})
        self.assertIn("durable unresolved", sessions.SYSTEM)
        self.assertIn("Prefer an existing candidate", sessions.SYSTEM)

    def test_render_text_preserves_plain_punctuation(self):
        self.assertEqual(sessions.render_text("api-v1.py: ready. (OK)!"), "api-v1.py: ready. (OK)!")
        rendered = sessions.render_text("## heading\n[[Fake]] <!-- comment --> ^fake-id")
        self.assertNotIn("\n", rendered)
        self.assertNotIn("[[", rendered)
        self.assertNotIn("<!--", rendered)
        self.assertNotIn("##", rendered)
        self.assertNotIn("^fake-id", rendered)

    def test_large_relevant_block_does_not_leave_evidence_budget_empty(self):
        query = "Embedding metadata migration"
        transcript = "## Assistant early ^large-match\nEmbedding metadata migration " + "x" * 18000 + "\n"
        transcript += "".join(f"## User time ^smaller-{i}\n" + "y" * 1700 + "\n" for i in range(10))
        transcript += "## Assistant final ^completion\nChanges delivered.\n"
        thoughts = {f"Thoughts/Candidate {i}.md": {"body": "z" * 350} for i in range(22)}
        payload = {"transcript": transcript, "candidate_thoughts": thoughts, "newer_sources": {},
            "existing_projects": [], "omitted_transcript_chars": 0,
            "omitted_thoughts": 0, "omitted_sources": 0, "omitted_projects": 0}
        ids = sessions.bound_payload(payload, [query])
        self.assertIn("completion", ids)
        self.assertNotIn("large-match", ids)
        self.assertEqual(len(payload["candidate_thoughts"]), 22)
        self.assertGreaterEqual(len(payload["transcript"].encode()), sessions.TRANSCRIPT_BYTES)
        self.assertEqual(payload["omitted_transcript_chars"], len(transcript) - len(payload["transcript"]))
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode()), sessions.INPUT_BYTES)

    def test_ollama_request_uses_think_false_and_payload_specific_schema(self):
        payload = {"transcript": self.body, "candidate_thoughts": {"Thoughts/Fix notes.md": {}},
                   "existing_projects": ["Projects/Obsidian second brain.md"]}
        envelope = {"message": {"content": json.dumps(self.answer)}, "done_reason": "stop"}
        with mock.patch.object(sessions.urllib.request, "urlopen",
                               return_value=io.BytesIO(json.dumps(envelope).encode())) as open_url:
            answer = sessions.ollama("http://127.0.0.1:11439/api/chat", "fixture", payload)
        request = json.loads(open_url.call_args.args[0].data)
        self.assertFalse(request["think"])
        self.assertFalse(request["stream"])
        self.assertEqual(request["options"]["num_predict"], 6144)
        schema = request["format"]
        self.assertFalse(schema["additionalProperties"])
        fields = schema["properties"]
        self.assertEqual(set(schema["required"]), set(self.answer))
        self.assertEqual(set(fields["summary"]["properties"]["evidence"]["items"]["enum"]),
                         {"msg-one", "msg-two", "part-one"})
        closure = fields["proposed_closures"]["items"]
        self.assertEqual(closure["properties"]["thought"]["enum"], ["Thoughts/Fix notes.md"])
        self.assertEqual(set(closure["properties"]["outcome"]["enum"]), sessions.OUTCOMES)
        self.assertEqual(set(closure["required"]), {"thought", "outcome", "reason", "evidence"})
        self.assertEqual(fields["project_links"]["items"]["enum"], ["Projects/Obsidian second brain.md"])
        self.assertEqual(fields["proposed_new_thoughts"]["maxItems"], 3)
        variants = fields["proposed_new_thoughts"]["items"]["anyOf"]
        self.assertEqual(set(variants[0]["properties"]["evidence"]["items"]["enum"]), {"msg-one", "part-one"})
        self.assertEqual(variants[1]["properties"]["evidence"]["items"]["enum"], ["msg-two"])
        self.assertEqual(variants[1]["properties"]["text"]["pattern"], "^Uncertain context: .+$")
        self.assertEqual(answer, self.answer)
        sessions.validate(answer, {"msg-one", "msg-two", "part-one"},
                          payload["candidate_thoughts"], payload["existing_projects"], {"msg-two"})
        empty = sessions.response_schema({**payload, "candidate_thoughts": {}, "existing_projects": []})
        self.assertEqual(empty["properties"]["proposed_closures"]["maxItems"], 0)
        self.assertEqual(empty["properties"]["project_links"]["maxItems"], 0)

    def test_api_failures_classified_without_private_content(self):
        payload = {"transcript": self.body, "candidate_thoughts": {}, "existing_projects": []}
        private = "PRIVATE_RESPONSE_MUST_NEVER_BE_LOGGED"
        for envelope, expected in (({"message": {"content": private}}, json.JSONDecodeError),
                                   ({"message": {"content": private}, "done_reason": "length"}, sessions.ReviewValidationError),
                                   ({"error": private}, sessions.ReviewValidationError)):
            with self.subTest(expected=expected):
                with mock.patch.object(sessions.urllib.request, "urlopen",
                        return_value=io.BytesIO(json.dumps(envelope).encode())), self.assertRaises(expected) as error:
                    sessions.ollama("http://127.0.0.1:11439/api/chat", "fixture", payload)
                label = sessions.safe_failure(error.exception, "model")
                self.assertNotIn(private, label)
                self.assertTrue(label.startswith(("JSON parse", "schema")))
        for error, kind in ((json.JSONDecodeError(private, private, 0), "JSON parse"),
                            (sessions.urllib.error.URLError(private), "transport"),
                            (sessions.ReviewValidationError("invalid evidence"), "schema"),
                            (sessions.ReviewValidationError(private), "schema")):
            def fail(url, model, payload, error=error):
                raise error
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(sessions.process(self.args, fail), 1)
            self.assertIn(kind, output.getvalue())
            self.assertNotIn(private, output.getvalue())


if __name__ == "__main__":
    unittest.main()
