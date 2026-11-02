"""Real-process scheduling and lifecycle proof, isolated from user sessions."""

import multiprocessing
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from contextlib import ExitStack, nullcontext

import context_chat_worker as worker


def hold_lock(state, ready, release, owner="A", database=None, conversation=None):
    os.environ["XDG_STATE_HOME"] = state
    with worker.scoped_lock(owner, database=database, conversation=conversation, timeout=2):
        ready.set()
        release.wait(5)


def select_job(state, database, gate, result, counter, revision="v1", owner="A", chat="chat"):
    os.environ["XDG_STATE_HOME"] = state
    ledger = Path(state) / (owner + chat + ".ledger")

    def check():
        return revision if ledger.exists() and ledger.read_text() == revision else None

    def work():
        with counter.get_lock():
            counter.value += 1
        gate.wait(5)
        ledger.write_text(revision)
        return revision

    try:
        result.put(worker.selected_work(owner, database, chat, revision, work, check=check, timeout=5))
    except Exception as exc:
        result.put(type(exc).__name__)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chat-worker-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.database = self.root / "native.db"
        self.database.touch()
        self.mp = multiprocessing.get_context("fork")

    def spawn(self, target, *args):
        process = self.mp.Process(target=target, args=args)
        process.start()

        def cleanup():
            if process.is_alive():
                process.terminate()
            process.join(3)
            if process.is_alive():
                process.kill()
                process.join(3)
        self.addCleanup(cleanup)
        return process

    def test_context_and_database_boundaries_and_bounded_wait(self):
        ready, release = self.mp.Event(), self.mp.Event()
        self.spawn(hold_lock, str(self.root), ready, release)
        self.assertTrue(ready.wait(2))
        start = time.monotonic()
        with worker.scoped_lock("B", timeout=.1):
            pass
        states = []
        with self.assertRaises(worker.Busy):
            with worker.scoped_lock("A", timeout=.08, on_state=states.append):
                self.fail("contended lock acquired")
        self.assertLess(time.monotonic() - start, .5)
        self.assertEqual(states, ["waiting_lock"])
        release.set()

    def test_family_lock_isolated_by_database_and_chat(self):
        other = self.root / "other.db"
        other.touch()
        with worker.scoped_lock("A", database=self.database, conversation="one"):
            with worker.scoped_lock("A", database=other, conversation="one", timeout=0):
                pass
            with worker.scoped_lock("A", database=self.database, conversation="two", timeout=0):
                pass
            with self.assertRaises(worker.Busy):
                with worker.scoped_lock("A", database=self.database, conversation="one", timeout=0):
                    pass

    def test_database_replacement_changes_incarnation(self):
        previous = worker.database_identity(self.database)
        replacement = self.root / "replacement"
        replacement.touch()
        replacement.replace(self.database)
        self.assertNotEqual(previous, worker.database_identity(self.database))

    def test_duplicate_selected_requests_execute_once(self):
        gate, counter, results = self.mp.Event(), self.mp.Value("i", 0), self.mp.Queue()
        processes = [self.spawn(select_job, str(self.root), str(self.database), gate, results, counter)
                     for _ in range(4)]
        until = time.monotonic() + 2
        while counter.value == 0 and time.monotonic() < until:
            time.sleep(.01)
        self.assertEqual(counter.value, 1)
        gate.set()
        self.assertEqual([results.get(timeout=3) for _ in processes], ["v1"] * 4)
        self.assertEqual(counter.value, 1)
        for process in processes:
            process.join(2)
            self.assertEqual(process.exitcode, 0)

    def test_blocked_conversation_does_not_block_another(self):
        gate, counter, results = self.mp.Event(), self.mp.Value("i", 0), self.mp.Queue()
        self.spawn(select_job, str(self.root), str(self.database), gate, results, counter)
        until = time.monotonic() + 2
        while counter.value == 0 and time.monotonic() < until:
            time.sleep(.01)
        self.assertEqual(worker.selected_work("A", self.database, "other", "v1", lambda: "ready",
                                             check=lambda: None, timeout=.1), "ready")
        gate.set()
        self.assertEqual(results.get(timeout=3), "v1")

    def test_different_revision_reexecutes_and_failure_not_cached(self):
        completed = {}
        calls = []
        for revision in ["v1", "v1", "v2"]:
            def work():
                calls.append(revision)
                completed["revision"] = revision
                return revision
            worker.selected_work("A", self.database, "chat", revision, work,
                                 check=lambda: revision if completed.get("revision") == revision else None)
        self.assertEqual(calls, ["v1", "v2"])
        with self.assertRaisesRegex(ValueError, "interrupted"):
            worker.selected_work("A", self.database, "chat", "v3",
                                 lambda: (_ for _ in ()).throw(ValueError("interrupted")), check=lambda: None)
        self.assertEqual(worker.selected_work("A", self.database, "chat", "v3", lambda: "v3",
                                             check=lambda: None), "v3")

    def test_follower_cancel_leaves_owner_running(self):
        gate, counter, results = self.mp.Event(), self.mp.Value("i", 0), self.mp.Queue()
        process = self.spawn(select_job, str(self.root), str(self.database), gate, results, counter)
        until = time.monotonic() + 2
        while counter.value == 0 and time.monotonic() < until:
            time.sleep(.01)
        cancel = threading.Event()
        timer = threading.Timer(.05, cancel.set)
        timer.start()
        with self.assertRaises(worker.Cancelled):
            worker.selected_work("A", self.database, "chat", "v1", lambda: self.fail("duplicate"),
                                 check=lambda: None, cancel=cancel)
        timer.join()
        self.assertTrue(process.is_alive())
        gate.set()
        self.assertEqual(results.get(timeout=3), "v1")

    def test_owner_death_releases_family_and_stale_priority_lease(self):
        gate, counter, results = self.mp.Event(), self.mp.Value("i", 0), self.mp.Queue()
        process = self.spawn(select_job, str(self.root), str(self.database), gate, results, counter)
        until = time.monotonic() + 2
        while counter.value == 0 and time.monotonic() < until:
            time.sleep(.01)
        process.kill()
        process.join(2)
        with worker.scoped_lock("A", priority="maintenance", timeout=.2):
            pass
        self.assertEqual(worker.selected_work("A", self.database, "chat", "v1", lambda: "recovered",
                                             check=lambda: None, timeout=.2), "recovered")

    def test_selected_priority_defers_maintenance_only_in_own_context(self):
        with worker._selected("A"):
            with self.assertRaises(worker.Busy):
                with worker.scoped_lock("A", priority="maintenance", timeout=0):
                    pass
            with worker.scoped_lock("B", priority="maintenance", timeout=0):
                pass

    def test_child_output_and_exit_code(self):
        result = worker.run_child([sys.executable, "-c", "import sys; print('x'*200000); print('err',file=sys.stderr)"])
        self.assertEqual(len(result.stdout.strip()), 200000)
        self.assertEqual(result.stderr.strip(), "err")
        with self.assertRaises(subprocess.CalledProcessError) as caught:
            worker.run_child([sys.executable, "-c", "raise SystemExit(7)"])
        self.assertEqual(caught.exception.returncode, 7)

    @staticmethod
    def stopped(pid):
        try:
            # Zombies are dead and cannot hold locks/transactions. PID1 may
            # defer reaping grandchildren in container test environments.
            return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith("Z")
        except FileNotFoundError:
            return True

    def command_with_grandchild(self, pidfile):
        grandchild = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(30)"
        script = ("import subprocess,sys,time; "
                  f"p=subprocess.Popen([sys.executable,'-c',{grandchild!r}]); "
                  f"open({str(pidfile)!r},'w').write(str(p.pid)); time.sleep(30)")
        return [sys.executable, "-c", script]

    def test_timeout_cleans_term_resistant_descendant(self):
        pidfile = self.root / "grandchild"
        start = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            worker.run_child(self.command_with_grandchild(pidfile), timeout=.35, grace=.1)
        self.assertLess(time.monotonic() - start, 1.5)
        self.assertTrue(self.stopped(int(pidfile.read_text())))

    def test_cancellation_cleans_child_group(self):
        pidfile = self.root / "grandchild"
        cancel = threading.Event()
        timer = threading.Timer(.35, cancel.set)
        timer.start()
        try:
            with self.assertRaises(worker.Cancelled):
                worker.run_child(self.command_with_grandchild(pidfile), cancel=cancel, grace=.1)
        finally:
            timer.join()
        self.assertTrue(self.stopped(int(pidfile.read_text())))

    def test_selected_deadline_propagates_to_native_work(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            worker.selected_work("A", self.database, "chat", "v1",
                lambda: worker.run_child([sys.executable, "-c", "import time; time.sleep(30)"], grace=.05),
                check=lambda: None, timeout=.15)
        self.assertIsNone(worker.operation_deadline())

    def test_expired_callback_never_reports_ready(self):
        states = []
        with self.assertRaises(worker.Busy):
            worker.selected_work("A", self.database, "chat", "v1",
                                 lambda: time.sleep(.04), check=lambda: None,
                                 timeout=.02, on_state=states.append)
        self.assertNotIn("ready", states)

    def test_normal_native_exit_also_cleans_stranded_descendants(self):
        pidfile = self.root / "stranded"
        args = self.command_with_grandchild(pidfile)
        args[-1] = "time.sleep(.1)".join(args[-1].rsplit("time.sleep(30)", 1))
        result = worker.run_child(args, timeout=2, grace=.1)
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.stopped(int(pidfile.read_text())))

    def test_abrupt_parent_death_closes_lifeline_and_cleans_grandchildren(self):
        pidfile = self.root / "orphan"
        script = ("import sys; sys.path.insert(0,sys.argv[1]); import context_chat_worker as w; "
                  "w.run_child(sys.argv[2:],timeout=30,grace=.1)")
        process = subprocess.Popen([sys.executable, "-B", "-c", script, str(Path(worker.__file__).parent),
                                    *self.command_with_grandchild(pidfile)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            until = time.monotonic() + 3
            while not pidfile.exists() and time.monotonic() < until:
                time.sleep(.01)
            self.assertTrue(pidfile.exists())
            pid = int(pidfile.read_text())
            process.kill()
            process.wait(timeout=2)
            until = time.monotonic() + 2
            while not self.stopped(pid) and time.monotonic() < until:
                time.sleep(.02)
            self.assertTrue(self.stopped(pid), "grandchild survived caller SIGKILL")
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)

    def checkpoint_fixture(self, reason, library_error=None):
        import persistence
        context = {"id": "12345678-1234-1234-1234-123456789abc", "path": str(self.root / "context")}
        tm = Mock(socket="isolated")
        session = {"id": "one", "name": "one", "windows": [], "layout": "0000,80x24,0,0,0"}
        events = []
        notifications = Mock()
        archive = Mock()
        archive.publish.side_effect = lambda *_args: (events.append("published") or {"id": "test"}, True)

        def sync(*_args, **kwargs):
            events.append("maintenance")
            if library_error:
                kwargs["errors"].append((context["id"], library_error))

        with ExitStack() as stack:
            for name, value in {
                "sockets": Mock(return_value=[tm]),
                "context_servers": Mock(return_value=[tm]),
                "context_targets": Mock(return_value=["$1"]),
                "capture_tmux": Mock(return_value=[(context, tm, session)]),
                "latest": Mock(return_value=None),
                "inventory": Mock(side_effect=lambda *_: {"windows": [], "warnings": []}),
                "normalize_layouts": Mock(),
                "checkpoint_store": Mock(return_value=archive),
                "context_lock": Mock(side_effect=lambda *_: nullcontext()),
                "lock": Mock(side_effect=nullcontext),
                "notify": notifications, "report": Mock(),
            }.items():
                stack.enter_context(patch.object(persistence, name, value))
            stack.enter_context(patch.object(persistence.ctl, "scan", return_value=[context]))
            stack.enter_context(patch.object(persistence.ctl, "selected_context", return_value=context))
            stack.enter_context(patch.object(persistence.chat_library, "sync_dirty", side_effect=sync))
            try:
                persistence.checkpoint(reason=reason, context_id=context["id"])
            except persistence.CheckpointError as exc:
                exc.add_note(str(notifications.call_args_list))
                raise
        return events

    def test_checkpoint_publishes_snapshot_before_closed_library_maintenance(self):
        self.assertEqual(self.checkpoint_fixture("periodic"), ["published", "maintenance"])

    def test_periodic_busy_library_defers_but_close_never_sweeps_libraries(self):
        self.assertEqual(self.checkpoint_fixture("periodic", worker.Busy("held")),
                         ["published", "maintenance"])
        self.assertEqual(self.checkpoint_fixture("close", worker.Busy("held")), ["published"])


if __name__ == "__main__":
    unittest.main()
