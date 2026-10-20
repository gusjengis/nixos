"""Publication crash, sync ordering, bounded ownership and actual no-op I/O proofs."""

import copy
import ctypes
import json
import os
import random
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import checkpoint_store as s


class Changes:
    """Linux inotify: detect transient writes/deletes, not only final contents."""
    def __init__(self, root):
        self.lib = ctypes.CDLL(None, use_errno=True)
        self.fd = self.lib.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1")
        for directory in [root, *(p for p in root.rglob("*") if p.is_dir())]:
            # MODIFY, ATTRIB, MOVED_FROM/TO, CREATE, DELETE, DELETE_SELF.
            if self.lib.inotify_add_watch(self.fd, os.fsencode(directory), 0xFC6) < 0:
                raise OSError(ctypes.get_errno(), "inotify_add_watch")

    def finish(self):
        try:
            try:
                return os.read(self.fd, 1024 * 1024)
            except BlockingIOError:
                return b""
        finally:
            os.close(self.fd)


def stats(root):
    return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file()}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="current-store-", dir="/tmp/opencode")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.store = s.Store(self.base / "synced", self.base / "local")
        self.tree = s.Tree({"buffer.txt": b"A" * s.CHUNK + b"B" * s.CHUNK + b"C" * s.CHUNK,
                            "chat/part.json": b'{"text":"first"}', "desktop.json": b"{}"})
        self.metadata = {"device": "alpha", "context_id": "test", "warnings": [], "created_ns": 1}

    def publish(self, expected=None, storage=None):
        return (storage or self.store).publish(self.tree, self.metadata, expected)

    def test_noop_has_no_transient_writes_or_mtime_changes(self):
        current, _ = self.publish()
        before = stats(self.base)
        audit = Changes(self.base)
        with patch.object(s, "atomic", side_effect=AssertionError("no-op attempted write")):
            for tick in range(50):
                self.metadata["created_ns"] = tick + 2
                saved, changed = self.publish(current)
                self.assertFalse(changed)
                self.assertEqual(saved, current)
        self.assertEqual(audit.finish(), b"")
        self.assertEqual(stats(self.base), before)

    def test_single_large_piece_change_reuses_other_chunks_and_artifacts(self):
        current, _ = self.publish()
        before = stats(self.store.directory / "objects")
        self.tree.files["buffer.txt"] = b"A" * s.CHUNK + b"X" + b"B" * (s.CHUNK - 1) + b"C" * s.CHUNK
        saved, changed = self.publish(current)
        self.assertTrue(changed)
        self.assertEqual(saved["artifacts"]["chat/part.json"], current["artifacts"]["chat/part.json"])
        old_chunks = current["artifacts"]["buffer.txt"]["chunks"]
        new_chunks = saved["artifacts"]["buffer.txt"]["chunks"]
        self.assertEqual(old_chunks[::2], new_chunks[::2])
        after = stats(self.store.directory / "objects")
        self.assertEqual(len(set(after) - set(before)), 1)
        for key in set(after) & set(before):
            self.assertEqual(after[key], before[key])
        self.assertFalse(self.store.object(old_chunks[1]).exists())

    def test_insertion_reuses_large_payload_suffix_instead_of_offset_rechunking(self):
        data = random.Random(42).randbytes(1024 * 1024)
        self.tree.files["buffer.txt"] = data
        old, _ = self.publish()
        self.tree.files["buffer.txt"] = data[:45000] + b"inserted bytes" + data[45000:]
        new, _ = self.publish(old)
        before = set(old["artifacts"]["buffer.txt"]["chunks"])
        after = set(new["artifacts"]["buffer.txt"]["chunks"])
        self.assertGreater(len(before & after), len(before) * .8)
        self.assertLess(len(after - before), 5)

    def test_many_edits_bound_objects_bytes_and_transaction_data(self):
        current, _ = self.publish()
        initial = stats(self.store.directory / "objects")
        for edit in range(150):
            self.tree.files["chat/part.json"] = s.canonical({"text": str(edit)})
            current, _ = self.publish(current)
        self.assertEqual(len(list((self.store.directory / "objects").iterdir())), len(initial))
        self.assertEqual({p.name for p in self.store.local.iterdir()}, {"witness.json", "objects"})
        self.assertEqual({p.name for p in self.store.directory.iterdir()}, {"objects", "current.json"})

    def test_crash_at_every_durable_publication_step(self):
        current, _ = self.publish()
        self.tree.files["chat/part.json"] = b"new"
        original = s.atomic
        calls = []
        with patch.object(s, "atomic", side_effect=lambda path, data: (calls.append(str(path)), original(path, data))[1]):
            self.publish(current)
        # Restore exact pre-transaction fixture for each crash point.
        for crash in range(len(calls)):
            with self.subTest(crash=crash):
                shutil.rmtree(self.base / "trial", ignore_errors=True)
                trial = s.Store(self.base / "trial/sync", self.base / "trial/local")
                old_tree = s.Tree({"part": b"old"})
                old, _ = trial.publish(old_tree, self.metadata, None)
                count = 0

                def interrupted(path, data, crash=crash):
                    nonlocal count
                    if count == crash:
                        raise OSError("power loss")
                    count += 1
                    original(path, data)

                with patch.object(s, "atomic", side_effect=interrupted):
                    try:
                        trial.publish(s.Tree({"part": b"new"}), self.metadata, old)
                    except OSError:
                        pass
                committed = trial.load()
                trial.validate(committed)
                self.assertIn((trial.view(committed) / "part").read_bytes(), (b"old", b"new"))
                trial.publish(s.Tree({"part": b"final"}), self.metadata, committed)
                self.assertEqual(len(list((trial.directory / "objects").iterdir())), 1)
                self.assertFalse((trial.local / "pending.json").exists())

    def test_incoming_unknown_object_survives_old_manifest_save(self):
        current, _ = self.publish()
        incoming = self.store.object(s.sha(b"future device object"))
        incoming.write_bytes(b"future device object")
        self.tree.files["chat/part.json"] = b"changed locally"
        self.publish(current)
        self.assertEqual(incoming.read_bytes(), b"future device object")

    def test_reordered_manifest_objects_and_deletions_report_incomplete(self):
        old, _ = self.publish()
        target = s.Store(self.base / "target/sync", self.base / "target/local")
        shutil.copytree(self.store.directory, target.directory)
        self.tree.files["chat/part.json"] = b"new"
        new, _ = self.publish(old)
        # Deletion can precede the new root. Never silently use old data.
        obsolete = old["artifacts"]["chat/part.json"]["chunks"][0]
        target.object(obsolete).unlink()
        with self.assertRaisesRegex(ValueError, "missing/corrupt"):
            target.validate(target.load())
        shutil.copyfile(self.store.directory / "current.json", target.directory / "current.json")
        with self.assertRaisesRegex(ValueError, "missing/corrupt"):
            target.validate(target.load())
        with self.assertRaisesRegex(ValueError, "missing/corrupt"):
            target.publish(self.tree, self.metadata, new)
        for obj in (self.store.directory / "objects").iterdir():
            shutil.copyfile(obj, target.directory / "objects" / obj.name)
        target.validate(target.load())

    def test_concurrent_root_preserves_local_divergence_and_blocks(self):
        old, _ = self.publish()
        other = s.Store(self.base / "other/sync", self.base / "other/local")
        shutil.copytree(self.store.directory, other.directory)
        self.tree.files["chat/part.json"] = b"local branch"
        local, _ = self.publish(old)
        remote, _ = other.publish(s.Tree({"remote": b"remote branch"}), {"device": "beta"}, old)
        shutil.copyfile(other.directory / "current.json", self.store.directory / "current.json")
        for obj in (other.directory / "objects").iterdir():
            shutil.copyfile(obj, self.store.directory / "objects" / obj.name)
        # A remote deletion can arrive before its divergent root. The local
        # single-current mirror must preserve bytes, not merely an unusable index.
        local_key = local["artifacts"]["chat/part.json"]["chunks"][0]
        self.store.object(local_key).unlink()
        with self.assertRaisesRegex(ValueError, "Divergent"):
            self.publish(remote)
        preserved = json.loads((self.store.directory / "conflicts" / (local["id"] + ".json")).read_text())
        self.assertEqual(preserved, local)
        self.store.validate(preserved)

    def test_sequential_device_use_accepts_dominating_clock(self):
        old, _ = self.publish()
        other = s.Store(self.base / "other/sync", self.base / "other/local")
        shutil.copytree(self.store.directory, other.directory)
        remote, _ = other.publish(s.Tree({"remote": b"remote"}), {"device": "beta"}, old)
        shutil.copytree(other.directory, self.store.directory, dirs_exist_ok=True)
        saved, _ = self.publish(remote)
        self.assertEqual(saved["clock"], {"alpha": 2, "beta": 1})
        self.assertFalse((self.store.directory / "conflicts").exists())

    def test_sync_fork_after_crash_before_local_ack_preserves_pending_root(self):
        old, _ = self.publish()
        remote = s.Store(self.base / "remote/sync", self.base / "remote/local")
        shutil.copytree(self.store.directory, remote.directory)
        original = s.atomic

        def fail_ack(path, data):
            if path == self.store.local / "witness.json":
                raise OSError("crash before local acknowledgement")
            original(path, data)

        self.tree.files["chat/part.json"] = b"locally published before crash"
        with patch.object(s, "atomic", side_effect=fail_ack), self.assertRaises(OSError):
            self.publish(old)
        candidate = self.store.load()
        fork, _ = remote.publish(s.Tree({"fork": b"remote fork"}), {"device": "beta"}, old)
        shutil.copytree(remote.directory, self.store.directory, dirs_exist_ok=True)
        with self.assertRaisesRegex(ValueError, "Divergent"):
            self.publish(fork)
        preserved = json.loads((self.store.directory / "conflicts" / (candidate["id"] + ".json")).read_text())
        self.store.validate(preserved)
        self.assertEqual(preserved, candidate)

    def test_incoming_root_during_object_writes_is_not_overwritten(self):
        old, _ = self.publish()
        remote = s.Store(self.base / "remote/sync", self.base / "remote/local")
        shutil.copytree(self.store.directory, remote.directory)
        incoming, _ = remote.publish(s.Tree({"remote": b"incoming"}), {"device": "beta"}, old)
        original = s.atomic
        delivered = False

        def deliver_during_write(path, data):
            nonlocal delivered
            original(path, data)
            if path.parent == self.store.directory / "objects" and not delivered:
                delivered = True
                shutil.copytree(remote.directory, self.store.directory, dirs_exist_ok=True)

        self.tree.files["chat/part.json"] = b"local new piece"
        with patch.object(s, "atomic", side_effect=deliver_during_write), self.assertRaisesRegex(ValueError, "changed during publication"):
            self.publish(old)
        self.assertEqual(self.store.load(), incoming)
        self.assertTrue((self.store.local / "pending.json").is_file())
        with self.assertRaisesRegex(ValueError, "Divergent"):
            self.publish(incoming)

    def test_sync_conflict_and_stale_capture_are_not_auto_selected(self):
        self.publish()
        with self.assertRaisesRegex(ValueError, "changed during capture"):
            self.publish(None)
        (self.store.directory / "current.sync-conflict-test.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "Divergent Syncthing"):
            self.store.load()

    def test_v1_gc_preserves_divergence_and_unknown_incoming_generations(self):
        selected = "generations/1-alpha-selected"
        self.metadata["migrated_from"] = selected
        self.publish()
        for identity, device in ((selected, "alpha"), ("generations/2-beta-divergent", "beta"),
                                 ("generations/3-beta-incoming", "beta")):
            directory = self.store.directory / identity
            directory.mkdir(parents=True)
            (directory / "manifest.json").write_text(json.dumps({"id": identity, "parent": None, "device": device}))
            (directory / "recovery.txt").write_text(identity)
        for device, identity in (("alpha", selected), ("beta", "generations/2-beta-divergent")):
            s.atomic(self.store.directory / "heads" / (device + ".json"), s.canonical({"generation": identity}))
        (self.store.directory / "generations/4-alpha-unpublished").mkdir()
        self.store.remove_v1()
        self.assertFalse((self.store.directory / selected).exists())
        self.assertFalse((self.store.directory / "generations/4-alpha-unpublished").exists())
        self.assertTrue((self.store.directory / "generations/3-beta-incoming/recovery.txt").is_file())
        preserved = self.store.directory / "legacy-conflicts/2-beta-divergent/recovery.txt"
        self.assertEqual(preserved.read_text(), "generations/2-beta-divergent")
        audit = Changes(self.base)
        self.store.remove_v1()
        self.assertEqual(audit.finish(), b"")

    def test_missing_corrupt_hash_and_escaping_artifacts_fail(self):
        current, _ = self.publish()
        key = current["artifacts"]["buffer.txt"]["chunks"][0]
        self.store.object(key).write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "missing/corrupt"):
            self.store.validate(current)
        for name in ("../escape", "/escape"):
            bad = copy.deepcopy(current)
            bad["artifacts"][name] = bad["artifacts"].pop("buffer.txt")
            s.atomic(self.store.directory / "current.json", s.canonical({"manifest": bad, "sha256": s.sha(s.canonical(bad))}))
            with self.assertRaisesRegex(ValueError, "escapes"):
                self.store.load()


if __name__ == "__main__":
    unittest.main()
